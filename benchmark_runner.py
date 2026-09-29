import os
import time
import json
import hashlib
import statistics
from decimal import Decimal
import psycopg2
from neo4j import GraphDatabase

# ==========================================================
# CONFIGURATION
# ==========================================================
SQL_USER = os.environ.get('DB_USER', 'admin')
SQL_PASSWORD = os.environ.get('DB_PASSWORD', 'supersecretpassword')
SQL_HOST = os.environ.get('DB_HOST', 'localhost')
SQL_PORT = os.environ.get('DB_PORT', '5432')
SQL_DB = 'flightdb'

NEO4J_URI = os.environ.get('NEO4J_URI', 'bolt://localhost:7687')
NEO4J_USER = os.environ.get('NEO4J_USER', 'neo4j')
NEO4J_PASSWORD = os.environ.get('NEO4J_PASSWORD', 'Leonardo1846461')
NEO4J_DB_A = 'flightdbSchemaA'
NEO4J_DB_B = 'flightdbsSchemaB'

WARMUP_RUNS = 2
TEST_RUNS = 5

# ==========================================================
# ALIGNED QUERY DEFINITIONS (7 Queries)
# ==========================================================
QUERIES = {
    "1_Point_to_Point_Agg": {
        "description": "Calculate average arrival delay and total flight count between JFK and LAX.",
        "sql": """
            SELECT AVG(f.arr_delay), COUNT(f.flight_id) 
            FROM flights f 
            JOIN airports a1 ON f.origin_airport_id = a1.airport_id 
            JOIN airports a2 ON f.dest_airport_id = a2.airport_id 
            WHERE a1.iata = 'JFK' AND a2.iata = 'LAX';
        """,
        "neo4j_A": """
            MATCH (src:Airport {iata: 'JFK'})-[f:FLIGHT_TO]->(dst:Airport {iata: 'LAX'}) 
            RETURN AVG(toInteger(f.arr_delay)), COUNT(f);
        """,
        "neo4j_B": """
            MATCH (src:Airport {iata: 'JFK'})-[f:FLIGHT_TO]->(dst:Airport {iata: 'LAX'}) 
            RETURN AVG(toInteger(f.arr_delay)), COUNT(f);
        """
    },
    
    "2.1_Reachability_Airport": {
        "description": "Find all unique destination airports reachable from JFK.",
        "sql": """
            SELECT DISTINCT a2.iata 
            FROM routes r 
            JOIN airports a1 ON r.source_airport_id = a1.airport_id 
            JOIN airports a2 ON r.destination_airport_id = a2.airport_id 
            WHERE a1.iata = 'JFK';
        """,
        "neo4j_A": """
            MATCH (src:Airport {iata: 'JFK'})-[:HAS_ROUTE]->(dst:Airport) 
            RETURN DISTINCT dst.iata;
        """,
        "neo4j_B": """
            MATCH (src:Airport {iata: 'JFK'})-[:ROUTE_ORIGIN]->(:Route)-[:ROUTE_DEST]->(dst:Airport) 
            RETURN DISTINCT dst.iata;
        """
    },
    
    "2.2_Reachability_Plane": {
        "description": "Find unique destinations reachable from JFK using Airbus A320 (iata '320').",
        "sql": """
            SELECT DISTINCT a2.iata 
            FROM routes r 
            JOIN airports a1 ON r.source_airport_id = a1.airport_id 
            JOIN airports a2 ON r.destination_airport_id = a2.airport_id 
            JOIN planes p ON r.plane_id = p.plane_id 
            WHERE a1.iata = 'JFK' AND p.iata_code = '320';
        """,
        "neo4j_A": """
            MATCH (src:Airport {iata: 'JFK'})-[r:HAS_ROUTE]->(dst:Airport) 
            MATCH (p:Plane {plane_id: r.plane_id}) 
            WHERE p.iata_code = '320' 
            RETURN DISTINCT dst.iata;
        """,
        "neo4j_B": """
            MATCH (src:Airport {iata: 'JFK'})-[:ROUTE_ORIGIN]->(rt:Route)-[:ROUTE_DEST]->(dst:Airport)
            MATCH (rt)-[:USES_PLANE]->(p:Plane) 
            WHERE p.iata_code = '320' 
            RETURN DISTINCT dst.iata;
        """
    },
    
    "3_Shortest_Path": {
        "description": "Shortest route path (up to 3 hops) from BGM to CDG.",
        "sql": """
            WITH RECURSIVE route_path(dest_id, hops, path) AS (
                SELECT r.destination_airport_id, 1, ARRAY[r.source_airport_id, r.destination_airport_id]
                FROM routes r 
                JOIN airports a ON r.source_airport_id = a.airport_id 
                WHERE a.iata = 'BGM'
                UNION ALL
                SELECT r.destination_airport_id, rp.hops + 1, rp.path || r.destination_airport_id
                FROM routes r 
                JOIN route_path rp ON r.source_airport_id = rp.dest_id 
                WHERE rp.hops < 3 AND NOT (r.destination_airport_id = ANY(rp.path))
            )
            SELECT MIN(hops) 
            FROM route_path rp 
            JOIN airports a ON rp.dest_id = a.airport_id 
            WHERE a.iata = 'CDG';
        """,
        "neo4j_A": """
            MATCH p = shortestPath((src:Airport {iata: 'BGM'})-[:HAS_ROUTE*1..3]->(dst:Airport {iata: 'CDG'})) 
            RETURN length(p);
        """,
        "neo4j_B": """
            MATCH p = shortestPath((src:Airport {iata: 'BGM'})-[:ROUTE_ORIGIN|ROUTE_DEST*1..6]->(dst:Airport {iata: 'CDG'})) 
            RETURN length(p) / 2;
        """
    },
    
    "4_Deep_Entity_Join": {
        "description": "Top 5 UK airlines by delayed flights flying Airbus aircraft.",
        "sql": """
            SELECT al.name AS airline, COUNT(f.flight_id) AS delayed_flights
            FROM flights f
            JOIN routes r ON f.route_id = r.route_id
            JOIN airlines al ON r.airline_id = al.airline_id
            JOIN countries c ON al.country_id = c.country_id
            JOIN planes p ON r.plane_id = p.plane_id
            WHERE f.arr_delay > 0 
              AND c.name = 'United Kingdom' 
              AND p.name ILIKE '%Airbus%'
            GROUP BY al.name
            ORDER BY delayed_flights DESC LIMIT 5;
        """,
        "neo4j_A": """
            MATCH (al:Airline)-[:BASED_IN]->(c:Country {name: 'United Kingdom'})
            MATCH (src:Airport)-[f:FLIGHT_TO]->(dst:Airport)
            WHERE toInteger(f.arr_delay) > 0
            MATCH (src)-[r:HAS_ROUTE {route_id: f.route_id, airline_id: al.airline_id}]->(dst)
            MATCH (p:Plane {plane_id: r.plane_id})
            WHERE toLower(p.name) CONTAINS 'airbus'
            RETURN al.name AS airline, COUNT(f) AS delayed_flights
            ORDER BY delayed_flights DESC LIMIT 5;
        """,
        "neo4j_B": """
            MATCH (c:Country {name: 'United Kingdom'})<-[:BASED_IN]-(al:Airline)<-[:OPERATED_BY]-(rt:Route)-[:USES_PLANE]->(p:Plane)
            WHERE toLower(p.name) CONTAINS 'airbus'
            MATCH (src:Airport)-[:ROUTE_ORIGIN]->(rt)-[:ROUTE_DEST]->(dst:Airport)
            MATCH (src)-[f:FLIGHT_TO {route_id: rt.route_id}]->(dst)
            WHERE toInteger(f.arr_delay) > 0
            RETURN al.name AS airline, COUNT(f) AS delayed_flights
            ORDER BY delayed_flights DESC LIMIT 5;
        """
    },
    
    "5.1_Centrality_All": {
        "description": "Top 10 most globally connected airports (by distinct outgoing routes).",
        "sql": """
            SELECT a.iata, COUNT(DISTINCT r.destination_airport_id) as degree 
            FROM routes r 
            JOIN airports a ON r.source_airport_id = a.airport_id 
            GROUP BY a.iata 
            ORDER BY degree DESC LIMIT 10;
        """,
        "neo4j_A": """
            MATCH (src:Airport)-[:HAS_ROUTE]->(dst:Airport) 
            RETURN src.iata, COUNT(DISTINCT dst) AS degree 
            ORDER BY degree DESC LIMIT 10;
        """,
        "neo4j_B": """
            MATCH (src:Airport)-[:ROUTE_ORIGIN]->(rt:Route)-[:ROUTE_DEST]->(dst:Airport) 
            RETURN src.iata, COUNT(DISTINCT dst) AS degree 
            ORDER BY degree DESC LIMIT 10;
        """
    },
    
    "5.2_Centrality_Exclude_US": {
        "description": "Top 10 connected airports, excluding routes flown by US-based airlines.",
        "sql": """
            SELECT a.iata, COUNT(DISTINCT r.destination_airport_id) as degree
            FROM routes r
            JOIN airports a ON r.source_airport_id = a.airport_id
            JOIN airlines al ON r.airline_id = al.airline_id
            JOIN countries c ON al.country_id = c.country_id
            WHERE c.name != 'United States'
            GROUP BY a.iata 
            ORDER BY degree DESC LIMIT 10;
        """,
        "neo4j_A": """
            MATCH (al:Airline)-[:BASED_IN]->(c:Country)
            WHERE c.name <> 'United States'
            WITH collect(al.airline_id) AS non_us_airlines
            MATCH (src:Airport)-[r:HAS_ROUTE]->(dst:Airport)
            WHERE r.airline_id IN non_us_airlines
            RETURN src.iata, COUNT(DISTINCT dst) AS degree
            ORDER BY degree DESC LIMIT 10;
        """,
        "neo4j_B": """
            MATCH (src:Airport)-[:ROUTE_ORIGIN]->(rt:Route)-[:ROUTE_DEST]->(dst:Airport)
            MATCH (rt)-[:OPERATED_BY]->(al:Airline)-[:BASED_IN]->(c:Country)
            WHERE c.name <> 'United States'
            RETURN src.iata, COUNT(DISTINCT dst) AS degree
            ORDER BY degree DESC LIMIT 10;
        """
    }
}

# ==========================================================
# EQUIVALENCE HELPERS
# ==========================================================
def normalize_value(v):
    if v is None:
        return None
    if isinstance(v, (float, Decimal)):
        return round(float(v), 2)
    if isinstance(v, int):
        return int(v)
    if isinstance(v, str):
        v_str = v.strip()
        # Coerce numeric strings like "3670" into standard integers
        if v_str.isdigit() or (v_str.startswith('-') and v_str[1:].isdigit()):
            return int(v_str)
        return v_str
    return str(v).strip()
    
def normalize_row(row):
    if isinstance(row, dict):
        return [normalize_value(v) for v in row.values()]
    elif isinstance(row, (list, tuple)):
        return [normalize_value(v) for v in row]
    return [normalize_value(row)]

def compute_answer_hash(records):
    if not records:
        return "EMPTY_RESULT", []
    normalized_data = [normalize_row(r) for r in records]
    normalized_data.sort(key=lambda x: str(x))
    serialized = json.dumps(normalized_data, sort_keys=True)
    return hashlib.sha256(serialized.encode('utf-8')).hexdigest(), normalized_data

# ==========================================================
# EXECUTION LOGIC
# ==========================================================
def execute_sql(conn, query, runs):
    times = []
    records = []
    with conn.cursor() as cur:
        for i in range(runs):
            start = time.perf_counter()
            cur.execute(query)
            res = cur.fetchall()
            times.append(time.perf_counter() - start)
            if i == runs - 1:
                records = res
    ans_hash, norm_data = compute_answer_hash(records)
    return times, len(norm_data), ans_hash

def execute_neo4j(driver, db_name, query, runs):
    times = []
    records = []
    for i in range(runs):
        start = time.perf_counter()
        with driver.session(database=db_name) as session:
            res = session.run(query).data()
        times.append(time.perf_counter() - start)
        if i == runs - 1:
            records = res
    ans_hash, norm_data = compute_answer_hash(records)
    return times, len(norm_data), ans_hash

def run_benchmarks():
    print("="*95)
    print(" INITIALIZING DATABASE CONNECTIONS")
    print("="*95)
    
    try:
        sql_conn = psycopg2.connect(host=SQL_HOST, port=SQL_PORT, user=SQL_USER, password=SQL_PASSWORD, dbname=SQL_DB)
        print("✅ Connected to PostgreSQL")
    except Exception as e:
        print(f"❌ PostgreSQL Connection Failed: {e}")
        return

    try:
        neo4j_driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        neo4j_driver.verify_connectivity()
        print("✅ Connected to Neo4j")
    except Exception as e:
        print(f"❌ Neo4j Connection Failed: {e}")
        return

    results = []

    print("\n" + "="*95)
    print(" STARTING BENCHMARKS WITH EQUIVALENCE VERIFICATION")
    print("="*95)

    for q_name, q_data in QUERIES.items():
        print(f"\n▶ Executing {q_name}: {q_data['description']}")
        
        # SQL
        try:
            execute_sql(sql_conn, q_data["sql"], WARMUP_RUNS)
            sql_times, sql_rows, sql_hash = execute_sql(sql_conn, q_data["sql"], TEST_RUNS)
            sql_avg = statistics.mean(sql_times)
            print(f"   SQL        : {sql_avg:.4f}s | Rows: {sql_rows} | Hash: {sql_hash[:10]}")
        except Exception as e:
            print(f"   SQL        : FAILED ({e})")
            sql_avg, sql_rows, sql_hash = None, 0, "ERROR"
            sql_conn.rollback()

        # Neo4j Schema A
        try:
            execute_neo4j(neo4j_driver, NEO4J_DB_A, q_data["neo4j_A"], WARMUP_RUNS)
            neo_a_times, neo_a_rows, neo_a_hash = execute_neo4j(neo4j_driver, NEO4J_DB_A, q_data["neo4j_A"], TEST_RUNS)
            neo_a_avg = statistics.mean(neo_a_times)
            print(f"   Schema A   : {neo_a_avg:.4f}s | Rows: {neo_a_rows} | Hash: {neo_a_hash[:10]}")
        except Exception as e:
            print(f"   Schema A   : FAILED ({e})")
            neo_a_avg, neo_a_rows, neo_a_hash = None, 0, "ERROR"

        # Neo4j Schema B
        try:
            execute_neo4j(neo4j_driver, NEO4J_DB_B, q_data["neo4j_B"], WARMUP_RUNS)
            neo_b_times, neo_b_rows, neo_b_hash = execute_neo4j(neo4j_driver, NEO4J_DB_B, q_data["neo4j_B"], TEST_RUNS)
            neo_b_avg = statistics.mean(neo_b_times)
            print(f"   Schema B   : {neo_b_avg:.4f}s | Rows: {neo_b_rows} | Hash: {neo_b_hash[:10]}")
        except Exception as e:
            print(f"   Schema B   : FAILED ({e})")
            neo_b_avg, neo_b_rows, neo_b_hash = None, 0, "ERROR"

        match_status = "✅ MATCH" if (sql_hash == neo_a_hash == neo_b_hash) else "❌ MISMATCH"
        print(f"   Equivalence Verification: {match_status}")

        results.append({
            "Query": q_name,
            "SQL": f"{sql_avg:.4f}s" if sql_avg else "ERR",
            "Schema_A": f"{neo_a_avg:.4f}s" if neo_a_avg else "ERR",
            "Schema_B": f"{neo_b_avg:.4f}s" if neo_b_avg else "ERR",
            "Match": match_status
        })

    sql_conn.close()
    neo4j_driver.close()

    print("\n" + "="*95)
    print(f"{'BENCHMARK SUMMARY WITH EQUIVALENCE CONTROL':^95}")
    print("="*95)
    print(f"{'Query Name':<28} | {'PostgreSQL':<12} | {'Neo4j Schema A':<14} | {'Neo4j Schema B':<14} | {'Answers':<10}")
    print("-" * 95)
    for r in results:
        print(f"{r['Query']:<28} | {r['SQL']:<12} | {r['Schema_A']:<14} | {r['Schema_B']:<14} | {r['Match']:<10}")
    print("="*95 + "\n")

if __name__ == "__main__":
    run_benchmarks()