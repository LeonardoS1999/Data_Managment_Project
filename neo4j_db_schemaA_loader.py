import os
import time
import pandas as pd
from neo4j import GraphDatabase
from neo4j.exceptions import ServiceUnavailable, ClientError

# ==========================================================
# CONFIGURATION / PATH DEFINITIONS
# ==========================================================
DATA_DIR = os.environ.get('DATA_DIR', 'DATA_USED')
NEO4J_URI = os.environ.get('NEO4J_URI', 'bolt://localhost:7687')
NEO4J_USER = os.environ.get('NEO4J_USER', 'neo4j')
NEO4J_PASSWORD = os.environ.get('NEO4J_PASSWORD', 'Leonardo1846461')
NEO4J_DATABASE = os.environ.get('NEO4J_DATABASE', 'flightdbSchemaA')

BATCH_SIZE = 10000

# Explicit SQL Type Rules for Symmetry
INT_COLS = {
    'country_id', 'airline_id', 'airport_id', 'plane_id', 'route_id',
    'source_airport_id', 'destination_airport_id', 'flight_id', 'flight_number',
    'dep_delay', 'arr_delay', 'air_time', 'distance', 'taxi_out', 'wheels_off',
    'sched_time_elapsed', 'actual_time_elapsed', 'wheels_on', 'taxi_in',
    'diverted', 'cancelled', 'air_system_delay', 'security_delay',
    'airline_delay', 'late_aircraft_delay', 'weather_delay',
    'origin_airport_id', 'dest_airport_id'
}

FLOAT_COLS = {'latitude', 'longitude', 'high_feet'}
BOOL_COLS = {'is_dafif'}
TIMESTAMP_COLS = {'dep_time', 'sched_dep_time', 'arr_time', 'sched_arr_time'}

# ==========================================================
# FUNCTION 1: CONNECT TO NEO4J
# ==========================================================
def get_neo4j_driver():
    print("FUNCTION_1: CONNECT TO NEO4J DATABASE\n")
    print(f"    Step 1: Attempting connection to {NEO4J_URI}...")
    step_start = time.time()
    try:
        driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        driver.verify_connectivity()
        print(f"            ✅ Connected successfully in {time.time() - step_start:.4f} seconds\n")
        return driver
    except ServiceUnavailable as e:
        print(f"            ❌ Connection failed: {e}")
        exit(1)

# ==========================================================
# FUNCTION 2: ENSURE TARGET DATABASE EXISTS
# ==========================================================
def ensure_database_exists(driver, db_name):
    print(f"FUNCTION_2: RECREATING DATABASE '{db_name}'\n")
    try:
        with driver.session(database="system") as session:
            print(f"    Step 1: Dropping database '{db_name}' if present...")
            step_start = time.time()
            session.run(f"DROP DATABASE {db_name} IF EXISTS WAIT")
            print(f"            ✅ Existing database dropped in {time.time() - step_start:.4f} seconds\n")

            print(f"    Step 2: Creating clean database '{db_name}'...")
            step_start = time.time()
            session.run(f"CREATE DATABASE {db_name} WAIT")
            print(f"            ✅ Database '{db_name}' is active and ready in {time.time() - step_start:.4f} seconds\n")
            
    except ClientError as e:
        print(f"            ❌ Database creation failed: {e}\n")
        raise e

# ==========================================================
# FUNCTION 3: CREATE CONSTRAINTS & INDEXES
# ==========================================================
def create_constraints(driver, db_name):
    print("FUNCTION_3: CREATING DATABASE CONSTRAINTS & INDEXES\n")
    print("    Step 1: Applying primary key uniqueness constraints...")
    step_start = time.time()
    
    constraints = [
        "CREATE CONSTRAINT IF NOT EXISTS FOR (c:Country) REQUIRE c.country_id IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (a:Airline) REQUIRE a.airline_id IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (ap:Airport) REQUIRE ap.airport_id IS UNIQUE",
        "CREATE CONSTRAINT IF NOT EXISTS FOR (p:Plane) REQUIRE p.plane_id IS UNIQUE"
    ]
    
    with driver.session(database=db_name) as session:
        for query in constraints:
            session.run(query)
            
    print(f"            ✅ Constraints applied in {time.time() - step_start:.4f} seconds\n")

def enforce_schema_types(df):
    for col in df.columns:
        if col in INT_COLS:
            df[col] = pd.to_numeric(df[col], errors='coerce').astype('Int64')
        elif col in FLOAT_COLS:
            df[col] = pd.to_numeric(df[col], errors='coerce').astype('float64')
        elif col in BOOL_COLS:
            df[col] = df[col].astype('boolean')
        elif col in TIMESTAMP_COLS:
            df[col] = pd.to_datetime(df[col], errors='coerce').dt.strftime('%Y-%m-%d %H:%M:%S')
    return df

def sanitize_dataframe(df):
    df = df.loc[:, ~df.columns.str.contains('^unnamed', case=False)]
    df.columns = (
        df.columns.str.strip()
        .str.replace('/', '_', regex=False)
        .str.replace('(', '_', regex=False)
        .str.replace(')', '', regex=False)
        .str.lower()
    )
    df = df.replace({'\\N': None, 'nan': None, 'NaN': None, 'None': None, '<NA>': None})
    
    # Drop denormalized columns explicitly to guarantee normalized ingestion
    denorm_cols = ['state', 'country', 'airline', 'source_airport', 'destination_airport', 
                   'equipment', 'plane_iata_icao', 'airlines_iata_icao', 
                   'source_airport_iata_icao', 'destination_airport_iata_icao']
    df = df.drop(columns=[c for c in denorm_cols if c in df.columns], errors='ignore')
    return df

def clean_batch_records(df):
    records = df.to_dict('records')
    cleaned = []
    for record in records:
        clean_rec = {}
        for k, v in record.items():
            if pd.isna(v) or v is None:
                clean_rec[k] = None
            elif hasattr(v, 'item'):
                clean_rec[k] = v.item()
            else:
                clean_rec[k] = v
        cleaned.append(clean_rec)
    return cleaned

# ==========================================================
# FUNCTION 4: INGEST CORE NODES
# ==========================================================
def load_nodes(driver, db_name):
    func_start = time.time()
    print("FUNCTION_4: INGESTING ENTITY NODES\n")

    step = 1
    node_files = [
        ('Country', 'countries.csv', 'country_id'),
        ('Airline', 'airlines.csv', 'airline_id'),
        ('Airport', 'merged_airports.csv', 'airport_id'),
        ('Plane', 'planes.csv', 'plane_id')
    ]
    
    for label, file_name, pk_col in node_files:
        step_start = time.time()
        file_path = os.path.join(DATA_DIR, file_name)
        print(f"    Step {step}: Loading {file_name} as ':{label}' nodes...")
        
        if not os.path.exists(file_path):
            print(f"            ❌ Error: {file_path} not found!\n")
            continue

        df = pd.read_csv(file_path, low_memory=False)
        df = sanitize_dataframe(df)
        df = enforce_schema_types(df)
        df = df.dropna(subset=[pk_col]).drop_duplicates(subset=[pk_col])

        query = f"""
        UNWIND $batch AS row
        MERGE (n:{label} {{{pk_col}: row.{pk_col}}})
        SET n += row
        """
        
        total_count = 0
        for chunk in [df[i:i+BATCH_SIZE] for i in range(0, len(df), BATCH_SIZE)]:
            records = clean_batch_records(chunk)
            with driver.session(database=db_name) as session:
                session.run(query, batch=records)
            total_count += len(records)

        print(f"            ✅ Created/Updated {total_count} ':{label}' nodes in {time.time() - step_start:.4f} seconds\n")
        step += 1

    print(f"    TOTAL NODE LOADING TIME: {time.time() - func_start:.4f} seconds\n")

# ==========================================================
# FUNCTION 5: INGEST RELATIONSHIPS
# ==========================================================
def load_relationships(driver, db_name):
    func_start = time.time()
    print("FUNCTION_5: INGESTING GRAPH RELATIONSHIPS\n")

    step_start = time.time()
    print("    Step 1: Connecting Airlines to Countries (:BASED_IN)...")
    file_path = os.path.join(DATA_DIR, 'airlines.csv')
    if os.path.exists(file_path):
        df = enforce_schema_types(sanitize_dataframe(pd.read_csv(file_path, low_memory=False)))
        df = df.dropna(subset=['airline_id', 'country_id'])

        query = """
        UNWIND $batch AS row
        MATCH (a:Airline {airline_id: row.airline_id})
        MATCH (c:Country {country_id: row.country_id})
        CREATE (a)-[:BASED_IN]->(c)
        """
        records = clean_batch_records(df)
        with driver.session(database=db_name) as session:
            session.run(query, batch=records)
        print(f"            ✅ Created {len(records)} :BASED_IN relationships in {time.time() - step_start:.4f} seconds\n")

    step_start = time.time()
    print("    Step 2: Connecting Airports to Countries (:LOCATED_IN)...")
    file_path = os.path.join(DATA_DIR, 'merged_airports.csv')
    if os.path.exists(file_path):
        df = enforce_schema_types(sanitize_dataframe(pd.read_csv(file_path, low_memory=False)))
        df = df.dropna(subset=['airport_id', 'country_id'])

        query = """
        UNWIND $batch AS row
        MATCH (ap:Airport {airport_id: row.airport_id})
        MATCH (c:Country {country_id: row.country_id})
        CREATE (ap)-[:LOCATED_IN]->(c)
        """
        records = clean_batch_records(df)
        with driver.session(database=db_name) as session:
            session.run(query, batch=records)
        print(f"            ✅ Created {len(records)} :LOCATED_IN relationships in {time.time() - step_start:.4f} seconds\n")

    step_start = time.time()
    print("    Step 3: Ingesting Routes as (:HAS_ROUTE) between Airports...")
    file_path = os.path.join(DATA_DIR, 'routes.csv')
    if os.path.exists(file_path):
        df = sanitize_dataframe(pd.read_csv(file_path, low_memory=False))
        df = enforce_schema_types(df)
        df = df.dropna(subset=['route_id', 'source_airport_id', 'destination_airport_id'])

        query = """
        UNWIND $batch AS row
        MATCH (src:Airport {airport_id: row.source_airport_id})
        MATCH (dst:Airport {airport_id: row.destination_airport_id})
        CREATE (src)-[r:HAS_ROUTE]->(dst)
        SET r += row
        """
        total_routes = 0
        for chunk in [df[i:i+BATCH_SIZE] for i in range(0, len(df), BATCH_SIZE)]:
            records = clean_batch_records(chunk)
            with driver.session(database=db_name) as session:
                session.run(query, batch=records)
            total_routes += len(records)
        print(f"            ✅ Created {total_routes} :HAS_ROUTE relationships in {time.time() - step_start:.4f} seconds\n")

    step_start = time.time()
    print("    Step 4: Ingesting Flights as (:FLIGHT_TO) between Airports...")
    file_path = os.path.join(DATA_DIR, 'merged_flights_cleaned.csv')
    if os.path.exists(file_path):
        query = """
        UNWIND $batch AS row
        MATCH (src:Airport {airport_id: row.origin_airport_id})
        MATCH (dst:Airport {airport_id: row.dest_airport_id})
        CREATE (src)-[f:FLIGHT_TO]->(dst)
        SET f += row
        """
        total_flights = 0
        for chunk in pd.read_csv(file_path, chunksize=BATCH_SIZE, low_memory=False):
            chunk = sanitize_dataframe(chunk)
            chunk = enforce_schema_types(chunk)
            chunk = chunk.dropna(subset=['flight_id', 'origin_airport_id', 'dest_airport_id'])

            records = clean_batch_records(chunk)
            with driver.session(database=db_name) as session:
                session.run(query, batch=records)
            total_flights += len(records)
            
        print(f"            ✅ Created {total_flights} :FLIGHT_TO relationships in {time.time() - step_start:.4f} seconds\n")

    print(f"    TOTAL RELATIONSHIP LOADING TIME: {time.time() - func_start:.4f} seconds\n")

# ==========================================================
# MAIN EXECUTION FLOW
# ==========================================================
if __name__ == '__main__':
    total_start_time = time.time()

    driver = get_neo4j_driver()
    ensure_database_exists(driver, NEO4J_DATABASE)
    create_constraints(driver, NEO4J_DATABASE)
    load_nodes(driver, NEO4J_DATABASE)
    load_relationships(driver, NEO4J_DATABASE)
    driver.close()
    
    print("="*80)
    print(f"SUCCESS: Graph database constructed in '{NEO4J_DATABASE}'!")
    print(f"TOTAL EXECUTION TIME: {time.time() - total_start_time:.4f} seconds")
    print("="*80 + "\n")