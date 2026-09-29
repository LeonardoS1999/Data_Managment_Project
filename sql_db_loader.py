import os
import time
import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError, SQLAlchemyError

# ==========================================================
# CONFIGURATION / PATH DEFINITIONS
# ==========================================================
DATA_DIR = os.environ.get('DATA_DIR', 'DATA_USED')

DB_USER = os.environ.get('DB_USER', 'admin')
DB_PASSWORD = os.environ.get('DB_PASSWORD', 'supersecretpassword')
DB_HOST = os.environ.get('DB_HOST', 'localhost')
DB_PORT = os.environ.get('DB_PORT', '5432')
TARGET_DB_NAME = 'flightdb'

LOAD_ORDER = [
    ('countries', 'countries.csv'),
    ('airlines', 'airlines.csv'),
    ('airports', 'merged_airports.csv'),
    ('planes', 'planes.csv'),
    ('routes', 'routes.csv'),
    ('flights', 'merged_flights_cleaned.csv')
]

PK_MAP = {
    'countries': 'country_id',
    'airlines': 'airline_id',
    'airports': 'airport_id',
    'planes': 'plane_id',
    'routes': 'route_id',
    'flights': 'flight_id'
}

# ==========================================================
# SQL SCHEMA DDL DEFINITIONS
# ==========================================================
DDL_SCHEMA = """
DROP TABLE IF EXISTS flights CASCADE;
DROP TABLE IF EXISTS routes CASCADE;
DROP TABLE IF EXISTS planes CASCADE;
DROP TABLE IF EXISTS airports CASCADE;
DROP TABLE IF EXISTS airlines CASCADE;
DROP TABLE IF EXISTS countries CASCADE;

-- 1. COUNTRIES TABLE
CREATE TABLE countries (
    country_id BIGINT PRIMARY KEY,
    name TEXT,
    iso_code TEXT,
    dafif_code TEXT
);

-- 2. AIRLINES TABLE
CREATE TABLE airlines (
    airline_id BIGINT PRIMARY KEY,
    name TEXT,
    alias TEXT,
    iata TEXT,
    icao TEXT,
    airline_callsign TEXT,
    country_id BIGINT,
    active TEXT
);

-- 3. AIRPORTS TABLE
CREATE TABLE airports (
    airport_id BIGINT PRIMARY KEY,
    name TEXT,
    city TEXT,
    country_id BIGINT,
    iata TEXT,
    icao TEXT,
    latitude DOUBLE PRECISION,
    longitude DOUBLE PRECISION,
    high_feet DOUBLE PRECISION,
    timezone TEXT,
    ora_legale TEXT,
    tz_database_timezone TEXT,
    is_dafif BOOLEAN
);

-- 4. PLANES TABLE
CREATE TABLE planes (
    plane_id BIGINT PRIMARY KEY,
    name TEXT,
    iata_code TEXT,
    icao_code TEXT
);

-- 5. ROUTES TABLE
CREATE TABLE routes (
    route_id BIGINT PRIMARY KEY,
    airline_id BIGINT,
    source_airport_id BIGINT,
    destination_airport_id BIGINT,
    plane_id BIGINT
);

-- 6. FLIGHTS TABLE
CREATE TABLE flights (
    flight_id BIGINT PRIMARY KEY,
    route_id BIGINT,
    dep_time TIMESTAMP,
    sched_dep_time TIMESTAMP,
    dep_delay BIGINT,
    arr_time TIMESTAMP,
    sched_arr_time TIMESTAMP,
    arr_delay BIGINT,
    flight_number BIGINT,
    tail_number TEXT,
    air_time BIGINT,
    distance BIGINT,
    taxi_out BIGINT,
    wheels_off BIGINT,            
    sched_time_elapsed BIGINT,
    actual_time_elapsed BIGINT,
    wheels_on BIGINT,             
    taxi_in BIGINT,
    diverted BIGINT,
    cancelled BIGINT,
    cancellation_reason TEXT,
    air_system_delay BIGINT,     
    security_delay BIGINT,       
    airline_delay BIGINT,        
    late_aircraft_delay BIGINT,  
    weather_delay BIGINT,        
    airline_id BIGINT,
    origin_airport_id BIGINT,
    dest_airport_id BIGINT
);
"""

# ==========================================================
# FOREIGN KEY CONSTRAINTS
# ==========================================================
FK_CONSTRAINTS = [
    ("airlines", "ALTER TABLE airlines ADD CONSTRAINT fk_airlines_country FOREIGN KEY (country_id) REFERENCES countries(country_id) ON DELETE SET NULL;"),
    ("airports", "ALTER TABLE airports ADD CONSTRAINT fk_airports_country FOREIGN KEY (country_id) REFERENCES countries(country_id) ON DELETE SET NULL;"),
    ("routes", "ALTER TABLE routes ADD CONSTRAINT fk_routes_airline FOREIGN KEY (airline_id) REFERENCES airlines(airline_id) ON DELETE SET NULL;"),
    ("routes", "ALTER TABLE routes ADD CONSTRAINT fk_routes_src_airport FOREIGN KEY (source_airport_id) REFERENCES airports(airport_id) ON DELETE SET NULL;"),
    ("routes", "ALTER TABLE routes ADD CONSTRAINT fk_routes_dst_airport FOREIGN KEY (destination_airport_id) REFERENCES airports(airport_id) ON DELETE SET NULL;"),
    ("routes", "ALTER TABLE routes ADD CONSTRAINT fk_routes_plane FOREIGN KEY (plane_id) REFERENCES planes(plane_id) ON DELETE SET NULL;"),
    ("flights", "ALTER TABLE flights ADD CONSTRAINT fk_flights_route FOREIGN KEY (route_id) REFERENCES routes(route_id) ON DELETE SET NULL;"),
    ("flights", "ALTER TABLE flights ADD CONSTRAINT fk_flights_airline FOREIGN KEY (airline_id) REFERENCES airlines(airline_id) ON DELETE SET NULL;"),
    ("flights", "ALTER TABLE flights ADD CONSTRAINT fk_flights_origin_airport FOREIGN KEY (origin_airport_id) REFERENCES airports(airport_id) ON DELETE SET NULL;"),
    ("flights", "ALTER TABLE flights ADD CONSTRAINT fk_flights_dest_airport FOREIGN KEY (dest_airport_id) REFERENCES airports(airport_id) ON DELETE SET NULL;")
]

# ==========================================================
# FUNCTION 1: CONNECT & CREATE DATABASE
# ==========================================================
def get_sql_engine(max_retries=5, delay=5):
    func_start = time.time()
    print("FUNCTION_1: CONNECT TO SQL DATABASE & CREATE DB\n")
    base_uri = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/postgres"
    target_uri = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{TARGET_DB_NAME}"
    
    print(f"    Step 1: Connecting to PostgreSQL server at {DB_HOST}:{DB_PORT}...")
    step_start = time.time()
    engine = create_engine(base_uri, isolation_level="AUTOCOMMIT")
    connected = False
    
    for attempt in range(1, max_retries + 1):
        try:
            with engine.connect() as conn:
                connected = True
                print(f"            ✅ Connected successfully in {time.time() - step_start:.4f} seconds\n")
                break
        except OperationalError:
            print(f"            ⏳ Attempt {attempt}/{max_retries} failed. Retrying in {delay}s...")
            time.sleep(delay)
        except SQLAlchemyError as e:
            print(f"            ❌ Connection failed: {e}")
            exit(1)
            
    if not connected:
        print("            ❌ Error: Server unreachable.")
        exit(1)
        
    print(f"    Step 2: Checking database '{TARGET_DB_NAME}'...")
    step_start = time.time()
    with engine.connect() as conn:
        result = conn.execute(text(f"SELECT 1 FROM pg_database WHERE datname = '{TARGET_DB_NAME}'"))
        if not result.scalar():
            conn.execute(text(f"CREATE DATABASE {TARGET_DB_NAME}"))
            print(f"            ✅ Database '{TARGET_DB_NAME}' created in {time.time() - step_start:.4f} seconds!\n")
        else:
            print(f"            ℹ️ Database '{TARGET_DB_NAME}' exists. Checked in {time.time() - step_start:.4f} seconds.\n")
            
    engine.dispose()
    print("="*80)
    print(f"SUCCESS: Database setup completed successfully, executed in {time.time() - func_start:.4f} seconds")
    print("="*80 + "\n")
    return create_engine(target_uri)

# ==========================================================
# FUNCTION 2: EXPLICIT DDL INITIALIZATION
# ==========================================================
def create_tables(engine):
    func_start = time.time()
    print("FUNCTION_2: EXPLICIT DDL INITIALIZATION\n")
    print("    Step 1: explicit CREATE TABLE queries with strict data types & PKs...")
    step_start = time.time()
    with engine.begin() as conn:
        conn.execute(text(DDL_SCHEMA))
    print(f"            ✅ Schema creation complete in {time.time() - step_start:.4f} seconds.\n")
    print("="*80)
    print(f"SUCCESS: Schema initialization completed successfully, executed in {time.time() - func_start:.4f} seconds")
    print("="*80 + "\n")

# ==========================================================
# FUNCTION 3: LOAD CSV DATA WITH CLEANING & SANITIZATION
# ==========================================================
def load_csv_to_sql(engine):
    func_start = time.time()
    print("FUNCTION_3: LOAD CSV DATA (APPEND TO PRE-CREATED SCHEMAS)\n")
    
    loaded_pks = {}
    i = 1
    
    for table_name, file_name in LOAD_ORDER:
        step_start = time.time()
        file_path = os.path.join(DATA_DIR, file_name)
        print(f"    Step {i}: Ingesting {file_name} -> table '{table_name}'...")
        
        if not os.path.exists(file_path):
            print(f"            ❌ Error: File {file_path} not found!\n")
            continue
            
        try:
            df = pd.read_csv(file_path, low_memory=False)
            
            # 1. Drop Pandas index artifacts ('unnamed: 0', 'unnamed:_3', etc.)
            df = df.loc[:, ~df.columns.str.contains('^unnamed', case=False)]
            
            # 2. Sanitize column names
            df.columns = (
                df.columns.str.strip()
                .str.replace('/', '_', regex=False)
                .str.replace('(', '_', regex=False)
                .str.replace(')', '', regex=False)
                .str.lower()
            )

            # 3. Drop Denormalized Columns securely if they still exist in raw files
            denorm_cols = ['state', 'country', 'airline', 'source_airport', 'destination_airport', 'equipment', 'plane_iata_icao', 'airlines_iata_icao', 'source_airport_iata_icao', 'destination_airport_iata_icao']
            df = df.drop(columns=[c for c in denorm_cols if c in df.columns], errors='ignore')

            # 4. Clean string NA values
            df = df.replace({'\\N': None, 'nan': None, 'NaN': None, 'None': None, '<NA>': None})
            
            # 5. Handle & Deduplicate Primary Keys
            pk_col = PK_MAP.get(table_name)
            if pk_col and pk_col in df.columns:
                df[pk_col] = pd.to_numeric(df[pk_col], errors='coerce')
                df = df.dropna(subset=[pk_col])
                df[pk_col] = df[pk_col].astype('int64')
                df = df.drop_duplicates(subset=[pk_col], keep='first')
                loaded_pks[table_name] = set(df[pk_col].tolist())
            
            # 6. Clean Orphaned Foreign Keys (prevent constraint failures)
            fk_mappings = {
                'country_id': 'countries',
                'airline_id': 'airlines',
                'source_airport_id': 'airports',
                'destination_airport_id': 'airports',
                'origin_airport_id': 'airports',
                'dest_airport_id': 'airports',
                'plane_id': 'planes',
                'route_id': 'routes'
            }
            
            for col, parent_table in fk_mappings.items():
                if col in df.columns and parent_table in loaded_pks:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
                    df.loc[~df[col].isin(loaded_pks[parent_table]), col] = None

            # 7. Specialized transformations for 'flights' table
            if table_name == 'flights':
                for ts_col in ['dep_time', 'sched_dep_time', 'arr_time', 'sched_arr_time']:
                    if ts_col in df.columns:
                        df[ts_col] = pd.to_datetime(df[ts_col], errors='coerce')

                bigint_cols = [
                    'wheels_off', 'wheels_on', 'dep_delay', 'arr_delay', 
                    'air_time', 'distance', 'taxi_out', 'taxi_in', 
                    'sched_time_elapsed', 'actual_time_elapsed', 'diverted', 'cancelled',
                    'air_system_delay', 'security_delay', 'airline_delay', 
                    'late_aircraft_delay', 'weather_delay'
                ]
                
                for col in bigint_cols:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors='coerce').astype('Int64')
            
            i = i + 1

            # 8. Append to SQL database
            df.to_sql(table_name, engine, if_exists='append', index=False, chunksize=10000)
            print(f"            ✅ Loaded {len(df)} rows into '{table_name}' in {time.time() - step_start:.4f} seconds\n")
        except Exception as e:
            print(f"            ❌ Error loading {file_name}: {e}\n")

    print("="*80)
    print(f"SUCCESS: CSV ingestion completed successfully, executed in {time.time() - func_start:.4f} seconds")
    print("="*80 + "\n")

# ==========================================================
# FUNCTION 4: APPLY FOREIGN KEY CONSTRAINTS
# ==========================================================
def apply_foreign_keys(engine):
    func_start = time.time()
    print("FUNCTION_4: APPLY FOREIGN KEY CONSTRAINTS\n")
    print("    Step 1: Appling foreign keys")
    with engine.begin() as conn:
        for table_name, fk_stmt in FK_CONSTRAINTS:
            step_start = time.time()
            try:
                conn.execute(text(fk_stmt))
                print(f"            ✅ Foreign key applied for table '{table_name}' in {time.time() - step_start:.4f} seconds")
            except Exception as e:
                print(f"            ⚠️ Warning: Could not apply FK on '{table_name}': {e}")
    print("\n" + "="*80)
    print(f"SUCCESS: Foreign keys applied successfully, executed in {time.time() - func_start:.4f} seconds")
    print("="*80 + "\n")

# ==========================================================
# MAIN EXECUTION FLOW
# ==========================================================
if __name__ == '__main__':
    total_start_time = time.time()

    engine = get_sql_engine()
    create_tables(engine)
    load_csv_to_sql(engine)
    apply_foreign_keys(engine)
    
    print("="*60)
    print("SUCCESS: Tables initialized, data loaded, & constraints set!")
    print(f"TOTAL EXECUTION TIME {time.time() - total_start_time:.4f} seconds")
    print("="*60 + "\n")