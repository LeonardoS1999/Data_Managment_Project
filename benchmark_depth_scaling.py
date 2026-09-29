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

WARMUP_RUNS = 1
TEST_RUNS = 5
MAX_DEPTH = 5  # Step-by-step depth range: 1 to 5 hops

# ==========================================================
# ALIGNED QUERY GENERATORS FOR HOPS / DEPTH
# ==========================================================
def get_sql_query(max_hops):
    return f"""
        WITH RECURSIVE route_path(src_id, dest_id, hops, path) AS (
            SELECT r.source_airport_id, r.destination_airport_id, 1, ARRAY[r.source_airport_id, r.destination_airport_id]
            FROM routes r
            JOIN airports a ON r.source_airport_id = a.airport_id
            WHERE a.iata IN ('JFK', 'LAX', 'ORD', 'ATL', 'DFW')
            
            UNION ALL
            
            SELECT rp.src_id, r.destination_airport_id, rp.hops + 1, rp.path || r.destination_airport_id
            FROM routes r
            JOIN route_path rp ON r.source_airport_id = rp.dest_id
            WHERE rp.hops < {max_hops} AND NOT (r.destination_airport_id = ANY(rp.path))
        )
        SELECT a1.iata AS src_code, a2.iata AS dst_code, MIN(rp.hops)
        FROM route_path rp
        JOIN airports a1 ON rp.src_id = a1.airport_id
        JOIN airports a2 ON rp.dest_id = a2.airport_id
        WHERE a2.iata IN ('LHR', 'CDG', 'FRA', 'AMS', 'MUC')
        GROUP BY a1.iata, a2.iata;
    """

def get_neo4j_a_query(max_hops):
    return f"""
        UNWIND ['JFK', 'LAX', 'ORD', 'ATL', 'DFW'] AS src_code
        UNWIND ['LHR', 'CDG', 'FRA', 'AMS', 'MUC'] AS dst_code
        MATCH (src:Airport {{iata: src_code}}), (dst:Airport {{iata: dst_code}})
        MATCH p = shortestPath((src)-[:HAS_ROUTE*1..{max_hops}]->(dst))
        RETURN src_code, dst_code, length(p);
    """

def get_neo4j_b_query(max_hops):
    max_rels = max_hops * 2
    return f"""
        UNWIND ['JFK', 'LAX', 'ORD', 'ATL', 'DFW'] AS src_code
        UNWIND ['LHR', 'CDG', 'FRA', 'AMS', 'MUC'] AS dst_code
        MATCH (src:Airport {{iata: src_code}}), (dst:Airport {{iata: dst_code}})
        MATCH p = shortestPath((src)-[:ROUTE_ORIGIN|ROUTE_DEST*1..{max_rels}]->(dst))
        RETURN src_code, dst_code, length(p) / 2;
    """

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

def run_depth_benchmark():
    print("="*95)
    print(" INITIALIZING DB CONNECTIONS FOR DEPTH SCALING TEST")
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
    print(f" STARTING DEPTH SCALING BENCHMARK WITH EQUIVALENCE CONTROL (Max Hops 1 to {MAX_DEPTH})")
    print("="*95)

    for depth in range(1, MAX_DEPTH + 1):
        print(f"\n▶ Testing Search Depth: {depth} Hop(s)...")

        sql_q = get_sql_query(depth)
        neo_a_q = get_neo4j_a_query(depth)
        neo_b_q = get_neo4j_b_query(depth)

        # SQL
        try:
            execute_sql(sql_conn, sql_q, WARMUP_RUNS)
            sql_times, sql_rows, sql_hash = execute_sql(sql_conn, sql_q, TEST_RUNS)
            sql_avg = f"{statistics.mean(sql_times):.4f}s"
            print(f"   SQL (Depth {depth})        : {sql_avg} | Rows: {sql_rows} | Hash: {sql_hash[:10]}")
        except Exception as e:
            err_msg = str(e).split('\n')[0]
            print(f"   SQL (Depth {depth})        : FAILED ({err_msg})")
            sql_avg, sql_rows, sql_hash = "FAILED", 0, "ERROR"
            sql_conn.rollback()

        # Schema A
        try:
            execute_neo4j(neo4j_driver, NEO4J_DB_A, neo_a_q, WARMUP_RUNS)
            neo_a_times, neo_a_rows, neo_a_hash = execute_neo4j(neo4j_driver, NEO4J_DB_A, neo_a_q, TEST_RUNS)
            neo_a_avg = f"{statistics.mean(neo_a_times):.4f}s"
            print(f"   Schema A (Depth {depth})   : {neo_a_avg} | Rows: {neo_a_rows} | Hash: {neo_a_hash[:10]}")
        except Exception as e:
            print(f"   Schema A (Depth {depth})   : FAILED ({e})")
            neo_a_avg, neo_a_rows, neo_a_hash = "FAILED", 0, "ERROR"

        # Schema B
        try:
            execute_neo4j(neo4j_driver, NEO4J_DB_B, neo_b_q, WARMUP_RUNS)
            neo_b_times, neo_b_rows, neo_b_hash = execute_neo4j(neo4j_driver, NEO4J_DB_B, neo_b_q, TEST_RUNS)
            neo_b_avg = f"{statistics.mean(neo_b_times):.4f}s"
            print(f"   Schema B (Depth {depth})   : {neo_b_avg} | Rows: {neo_b_rows} | Hash: {neo_b_hash[:10]}")
        except Exception as e:
            print(f"   Schema B (Depth {depth})   : FAILED ({e})")
            neo_b_avg, neo_b_rows, neo_b_hash = "FAILED", 0, "ERROR"

        match_status = "✅ MATCH" if (sql_hash == neo_a_hash == neo_b_hash) else "❌ MISMATCH"
        print(f"   Equivalence Control (Depth {depth}): {match_status}")

        results.append({
            "Depth": f"{depth} Hop(s)",
            "SQL": sql_avg,
            "Schema_A": neo_a_avg,
            "Schema_B": neo_b_avg,
            "Match": match_status
        })

    sql_conn.close()
    neo4j_driver.close()

    print("\n" + "="*95)
    print(f"{'QUERY 3 DEPTH SCALING SUMMARY WITH EQUIVALENCE CONTROL':^95}")
    print("="*95)
    print(f"{'Max Path Depth':<16} | {'PostgreSQL':<16} | {'Neo4j Schema A':<16} | {'Neo4j Schema B':<16} | {'Answers':<10}")
    print("-" * 95)
    for r in results:
        print(f"{r['Depth']:<16} | {r['SQL']:<16} | {r['Schema_A']:<16} | {r['Schema_B']:<16} | {r['Match']:<10}")
    print("="*95 + "\n")

if __name__ == "__main__":
    run_depth_benchmark()