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

# ==========================================================
# ALIGNED HEAVY GLOBAL QUERY DEFINITIONS (6 QUERIES)
# ==========================================================
QUERIES = {

    "1_Global_Pair_Agg": {
        "description": "Aggregate avg delay & flight count for ALL airport pairs with >50 flights.",
        "sql": """
            SELECT f.origin_airport_id::integer AS origin_airport_id, 
                   f.dest_airport_id::integer AS dest_airport_id, 
                   AVG(f.arr_delay) AS avg_delay, 
                   COUNT(*)::integer AS flight_cnt
            FROM flights f
            JOIN airports a1 ON f.origin_airport_id = a1.airport_id
            JOIN airports a2 ON f.dest_airport_id = a2.airport_id
            GROUP BY f.origin_airport_id, f.dest_airport_id
            HAVING COUNT(*) > 50;
        """,
        "neo4j_A": """
            MATCH (src:Airport)-[f:FLIGHT_TO]->(dst:Airport)
            WHERE src.airport_id IS NOT NULL AND dst.airport_id IS NOT NULL
            WITH toInteger(src.airport_id) AS origin_airport_id,
                 toInteger(dst.airport_id) AS dest_airport_id,
                 avg(toFloat(f.arr_delay)) AS avg_delay,
                 count(f) AS flight_cnt
            WHERE flight_cnt > 50
            RETURN origin_airport_id,
                   dest_airport_id,
                   avg_delay,
                   flight_cnt;
        """,
        "neo4j_B": """
            MATCH (src:Airport)-[f:FLIGHT_TO]->(dst:Airport)
            WHERE src.airport_id IS NOT NULL AND dst.airport_id IS NOT NULL
            WITH toInteger(src.airport_id) AS origin_airport_id,
                 toInteger(dst.airport_id) AS dest_airport_id,
                 avg(toFloat(f.arr_delay)) AS avg_delay,
                 count(f) AS flight_cnt
            WHERE flight_cnt > 50
            RETURN origin_airport_id,
                   dest_airport_id,
                   avg_delay,
                   flight_cnt;
        """
    },

    "2_Global_2Hop_Reachability": {
        "description": "Exact 2-hop reachable destination counts for ALL US airports.",
        "sql": """
            SELECT a1.iata AS origin, COUNT(DISTINCT r2.destination_airport_id) AS reachable_2hop
            FROM airports a1
            JOIN countries c ON a1.country_id = c.country_id
            JOIN routes r1 ON a1.airport_id = r1.source_airport_id
            JOIN routes r2 ON r1.destination_airport_id = r2.source_airport_id
            WHERE c.name = 'United States'
            GROUP BY a1.iata;
        """,
        "neo4j_A": """
            MATCH (c:Country {name: 'United States'})<-[:LOCATED_IN]-(src:Airport)
            MATCH (src)-[:HAS_ROUTE*2..2]->(dst:Airport)
            RETURN src.iata, COUNT(DISTINCT dst) AS reachable_2hop;
        """,
        "neo4j_B": """
            MATCH (c:Country {name: 'United States'})<-[:LOCATED_IN]-(src:Airport)
            MATCH (src)-[:ROUTE_ORIGIN|ROUTE_DEST*4..4]->(dst:Airport)
            RETURN src.iata, COUNT(DISTINCT dst) AS reachable_2hop;
        """
    },

    "3_Batch_Shortest_Paths": {
        "description": "Shortest paths between Top 5 US hubs and Top 5 European hubs (25 pairs).",
        "sql": """
            EXPLAIN ANALYZE 
            -- paste your Depth 3 SQL query here
            WITH RECURSIVE route_path(src_id, dest_id, hops, path) AS (
                SELECT r.source_airport_id, r.destination_airport_id, 1, ARRAY[r.source_airport_id, r.destination_airport_id]
                FROM routes r
                JOIN airports a ON r.source_airport_id = a.airport_id
                WHERE a.iata IN ('JFK', 'LAX', 'ORD', 'ATL', 'DFW')
                
                UNION ALL
                
                SELECT rp.src_id, r.destination_airport_id, rp.hops + 1, rp.path || r.destination_airport_id
                FROM routes r
                JOIN route_path rp ON r.source_airport_id = rp.dest_id
                WHERE rp.hops < 3 AND NOT (r.destination_airport_id = ANY(rp.path))
                
            )
            SELECT a1.iata AS src_code, a2.iata AS dst_code, MIN(rp.hops)
            FROM route_path rp
            JOIN airports a1 ON rp.src_id = a1.airport_id
            JOIN airports a2 ON rp.dest_id = a2.airport_id
            WHERE a2.iata IN ('LHR', 'CDG', 'FRA', 'AMS', 'MUC')
            GROUP BY a1.iata, a2.iata;
        """,
        "neo4j_A": """
            UNWIND ['JFK', 'LAX', 'ORD', 'ATL', 'DFW'] AS src_code
            UNWIND ['LHR', 'CDG', 'FRA', 'AMS', 'MUC'] AS dst_code
            MATCH (src:Airport {iata: src_code}), (dst:Airport {iata: dst_code})
            MATCH p = shortestPath((src)-[:HAS_ROUTE*1..3]->(dst))
            RETURN src_code, dst_code, length(p);
        """,
        "neo4j_B": """
            UNWIND ['JFK', 'LAX', 'ORD', 'ATL', 'DFW'] AS src_code
            UNWIND ['LHR', 'CDG', 'FRA', 'AMS', 'MUC'] AS dst_code
            MATCH (src:Airport {iata: src_code}), (dst:Airport {iata: dst_code})
            MATCH p = shortestPath((src)-[:ROUTE_ORIGIN|ROUTE_DEST*1..6]->(dst))
            RETURN src_code, dst_code, length(p) / 2;
        """
    },

    "4_Global_Deep_Entity_Join": {
        "description": "Total delayed flights grouped by Country and Plane Type globally across full dataset (LIMITED 20).",
        "sql": """
            SELECT c.name AS country, p.name AS plane, COUNT(f.flight_id) AS total_delays
            FROM flights f
            JOIN routes r ON f.route_id = r.route_id
            JOIN airlines al ON r.airline_id = al.airline_id
            JOIN countries c ON al.country_id = c.country_id
            JOIN planes p ON r.plane_id = p.plane_id
            WHERE f.arr_delay > 15
            GROUP BY c.name, p.name
            ORDER BY total_delays DESC LIMIT 20;
        """,
        "neo4j_A": """
            MATCH (al:Airline)-[:BASED_IN]->(c:Country)
            MATCH (src:Airport)-[f:FLIGHT_TO]->(dst:Airport)
            WHERE toInteger(f.arr_delay) > 15
            MATCH (src)-[r:HAS_ROUTE {route_id: f.route_id, airline_id: al.airline_id}]->(dst)
            MATCH (p:Plane {plane_id: r.plane_id})
            RETURN c.name AS country, p.name AS plane, COUNT(f) AS total_delays
            ORDER BY total_delays DESC LIMIT 20;
        """,
        "neo4j_B": """
            MATCH (c:Country)<-[:BASED_IN]-(al:Airline)<-[:OPERATED_BY]-(rt:Route)-[:USES_PLANE]->(p:Plane)
            MATCH (src:Airport)-[:ROUTE_ORIGIN]->(rt)-[:ROUTE_DEST]->(dst:Airport)
            MATCH (src)-[f:FLIGHT_TO {route_id: rt.route_id}]->(dst)
            WHERE toInteger(f.arr_delay) > 15
            RETURN c.name AS country, p.name AS plane, COUNT(f) AS total_delays
            ORDER BY total_delays DESC LIMIT 20;
        """
    },

    "5.1_2Hop_Centrality_NoFilter": {
        "description": "2-hop reachable network size for ALL global airports (WITHOUT FILTERS).",
        "sql": """
            SELECT a1.iata, COUNT(DISTINCT r2.destination_airport_id) AS reach_2hop
            FROM airports a1
            JOIN routes r1 ON a1.airport_id = r1.source_airport_id
            JOIN routes r2 ON r1.destination_airport_id = r2.source_airport_id
            GROUP BY a1.iata
            ORDER BY reach_2hop DESC LIMIT 20;
        """,
        "neo4j_A": """
            MATCH (src:Airport)-[:HAS_ROUTE]->(mid:Airport)-[:HAS_ROUTE]->(dst:Airport)
            RETURN src.iata, COUNT(DISTINCT dst) AS reach_2hop
            ORDER BY reach_2hop DESC LIMIT 20;
        """,
        "neo4j_B": """
            MATCH (src:Airport)-[:ROUTE_ORIGIN]->(r1:Route)-[:ROUTE_DEST]->(mid:Airport)
            MATCH (mid)-[:ROUTE_ORIGIN]->(r2:Route)-[:ROUTE_DEST]->(dst:Airport)
            RETURN src.iata, COUNT(DISTINCT dst) AS reach_2hop
            ORDER BY reach_2hop DESC LIMIT 20;
        """
    },

    "5.2_2Hop_Centrality_WithFilter": {
        "description": "2-hop reachable network size for ALL global airports (WITH FILTERS: Exclude US Airlines).",
        "sql": """
            WITH non_us_routes AS (
                SELECT r.source_airport_id, r.destination_airport_id
                FROM routes r
                JOIN airlines al ON r.airline_id = al.airline_id
                JOIN countries c ON al.country_id = c.country_id
                WHERE c.name != 'United States'
            )
            SELECT a1.iata, COUNT(DISTINCT r2.destination_airport_id) AS reach_2hop
            FROM airports a1
            JOIN non_us_routes r1 ON a1.airport_id = r1.source_airport_id
            JOIN non_us_routes r2 ON r1.destination_airport_id = r2.source_airport_id
            GROUP BY a1.iata
            ORDER BY reach_2hop DESC LIMIT 20;
        """,
        "neo4j_A": """
            MATCH (al:Airline)-[:BASED_IN]->(c:Country)
            WHERE c.name <> 'United States'
            WITH collect(al.airline_id) AS non_us_airlines
            MATCH (src:Airport)-[r1:HAS_ROUTE]->(mid:Airport)-[r2:HAS_ROUTE]->(dst:Airport)
            WHERE r1.airline_id IN non_us_airlines AND r2.airline_id IN non_us_airlines
            RETURN src.iata, COUNT(DISTINCT dst) AS reach_2hop
            ORDER BY reach_2hop DESC LIMIT 20;
        """,
        "neo4j_B": """
            MATCH (src:Airport)-[:ROUTE_ORIGIN]->(r1:Route)-[:ROUTE_DEST]->(mid:Airport)
            MATCH (mid)-[:ROUTE_ORIGIN]->(r2:Route)-[:ROUTE_DEST]->(dst:Airport)
            MATCH (r1)-[:OPERATED_BY]->(al1:Airline)-[:BASED_IN]->(c1:Country)
            MATCH (r2)-[:OPERATED_BY]->(al2:Airline)-[:BASED_IN]->(c2:Country)
            WHERE c1.name <> 'United States' AND c2.name <> 'United States'
            RETURN src.iata, COUNT(DISTINCT dst) AS reach_2hop
            ORDER BY reach_2hop DESC LIMIT 20;
        """
    },

    "6_DAFIF_vs_Civilian_Airfields": {
        "description": "Aggregate total flights and average delay grouped by DAFIF airfield status.",
        "sql": """
            SELECT a.is_dafif, 
                   COUNT(f.flight_id)::integer AS total_flights, 
                   AVG(f.arr_delay) AS avg_delay
            FROM flights f
            JOIN airports a ON f.origin_airport_id = a.airport_id
            GROUP BY a.is_dafif;
        """,
        "neo4j_A": """
            MATCH (src:Airport)-[f:FLIGHT_TO]->(dst:Airport)
            RETURN src.is_dafif AS is_dafif, 
                   COUNT(f) AS total_flights, 
                   AVG(toFloat(f.arr_delay)) AS avg_delay;
        """,
        "neo4j_B": """
            MATCH (src:Airport)-[f:FLIGHT_TO]->(dst:Airport)
            RETURN src.is_dafif AS is_dafif, 
                   COUNT(f) AS total_flights, 
                   AVG(toFloat(f.arr_delay)) AS avg_delay;
        """
    },

    "7_Delay_Reason_Breakdown": {
        "description": "Count occurrences of delay reasons (Carrier, Weather, NAS, Security, Late Aircraft).",
        "sql": """
            SELECT 
                SUM(CASE WHEN airline_delay > 0 THEN 1 ELSE 0 END)::integer AS carrier_delays,
                SUM(CASE WHEN weather_delay > 0 THEN 1 ELSE 0 END)::integer AS weather_delays,
                SUM(CASE WHEN air_system_delay > 0 THEN 1 ELSE 0 END)::integer AS nas_delays,
                SUM(CASE WHEN security_delay > 0 THEN 1 ELSE 0 END)::integer AS security_delays,
                SUM(CASE WHEN late_aircraft_delay > 0 THEN 1 ELSE 0 END)::integer AS late_aircraft_delays
            FROM flights
            WHERE arr_delay > 0;
        """,
        "neo4j_A": """
            MATCH ()-[f:FLIGHT_TO]->()
            WHERE f.arr_delay IS NOT NULL AND toInteger(f.arr_delay) > 0
            RETURN 
                SUM(CASE WHEN f.airline_delay IS NOT NULL AND toInteger(f.airline_delay) > 0 THEN 1 ELSE 0 END) AS carrier_delays,
                SUM(CASE WHEN f.weather_delay IS NOT NULL AND toInteger(f.weather_delay) > 0 THEN 1 ELSE 0 END) AS weather_delays,
                SUM(CASE WHEN f.air_system_delay IS NOT NULL AND toInteger(f.air_system_delay) > 0 THEN 1 ELSE 0 END) AS nas_delays,
                SUM(CASE WHEN f.security_delay IS NOT NULL AND toInteger(f.security_delay) > 0 THEN 1 ELSE 0 END) AS security_delays,
                SUM(CASE WHEN f.late_aircraft_delay IS NOT NULL AND toInteger(f.late_aircraft_delay) > 0 THEN 1 ELSE 0 END) AS late_aircraft_delays;
        """,
        "neo4j_B": """
            MATCH ()-[f:FLIGHT_TO]->()
            WHERE f.arr_delay IS NOT NULL AND toInteger(f.arr_delay) > 0
            RETURN 
                SUM(CASE WHEN f.airline_delay IS NOT NULL AND toInteger(f.airline_delay) > 0 THEN 1 ELSE 0 END) AS carrier_delays,
                SUM(CASE WHEN f.weather_delay IS NOT NULL AND toInteger(f.weather_delay) > 0 THEN 1 ELSE 0 END) AS weather_delays,
                SUM(CASE WHEN f.air_system_delay IS NOT NULL AND toInteger(f.air_system_delay) > 0 THEN 1 ELSE 0 END) AS nas_delays,
                SUM(CASE WHEN f.security_delay IS NOT NULL AND toInteger(f.security_delay) > 0 THEN 1 ELSE 0 END) AS security_delays,
                SUM(CASE WHEN f.late_aircraft_delay IS NOT NULL AND toInteger(f.late_aircraft_delay) > 0 THEN 1 ELSE 0 END) AS late_aircraft_delays;
        """
    },

    "8_MultiYear_Comparison_2013_2015": {
        "description": "Compare flight metrics, delays, and route coverage between years.",
        "sql": """
            SELECT 
                EXTRACT(YEAR FROM f.dep_time)::integer AS flight_year,
                COUNT(f.flight_id)::integer AS total_flights,
                AVG(f.arr_delay) AS avg_arr_delay,
                COUNT(DISTINCT f.route_id)::integer AS active_routes
            FROM flights f
            WHERE f.dep_time IS NOT NULL
            GROUP BY EXTRACT(YEAR FROM f.dep_time)
            ORDER BY flight_year;
        """,
        "neo4j_A": """
            MATCH ()-[f:FLIGHT_TO]->()
            WHERE f.dep_time IS NOT NULL AND f.dep_time <> ''
            WITH toInteger(left(f.dep_time, 4)) AS flight_year, f
            RETURN 
                flight_year, 
                COUNT(f) AS total_flights, 
                AVG(toFloat(f.arr_delay)) AS avg_arr_delay, 
                COUNT(DISTINCT toInteger(f.route_id)) AS active_routes
            ORDER BY flight_year;
        """,
        "neo4j_B": """
            MATCH ()-[f:FLIGHT_TO]->()
            WHERE f.dep_time IS NOT NULL AND f.dep_time <> ''
            WITH toInteger(left(f.dep_time, 4)) AS flight_year, f
            RETURN 
                flight_year, 
                COUNT(f) AS total_flights, 
                AVG(toFloat(f.arr_delay)) AS avg_arr_delay, 
                COUNT(DISTINCT toInteger(f.route_id)) AS active_routes
            ORDER BY flight_year;
        """
    },

    "9_JFK_Route_Airline_Plane_Coverage": {
        "description": "Count distinct destination airports reachable from JFK grouped by Airline Name and Plane Model.",
        "sql": """
            SELECT al.name AS airline, 
                   p.name AS plane, 
                   COUNT(DISTINCT r.destination_airport_id)::integer AS reachable_destinations
            FROM routes r
            JOIN airports a ON r.source_airport_id = a.airport_id
            JOIN airlines al ON r.airline_id = al.airline_id
            JOIN planes p ON r.plane_id = p.plane_id
            WHERE a.iata = 'JFK'
            GROUP BY al.name, p.name
            ORDER BY reachable_destinations DESC;
        """,
        "neo4j_A": """
            MATCH (src:Airport {iata: 'JFK'})-[r:HAS_ROUTE]->(dst:Airport)
            MATCH (al:Airline {airline_id: r.airline_id})
            MATCH (p:Plane {plane_id: r.plane_id})
            RETURN al.name AS airline, 
                   p.name AS plane, 
                   COUNT(DISTINCT dst) AS reachable_destinations
            ORDER BY reachable_destinations DESC;
        """,
        "neo4j_B": """
            MATCH (src:Airport {iata: 'JFK'})-[:ROUTE_ORIGIN]->(rt:Route)-[:ROUTE_DEST]->(dst:Airport)
            MATCH (rt)-[:OPERATED_BY]->(al:Airline)
            MATCH (rt)-[:USES_PLANE]->(p:Plane)
            RETURN al.name AS airline, 
                   p.name AS plane, 
                   COUNT(DISTINCT dst) AS reachable_destinations
            ORDER BY reachable_destinations DESC;
        """
    },

    "10_Global_2Hop_Same_Fleet": {
        "description": "Global heavy self-join: Count all 2-hop route combinations (A->B->C) operated by the exact same airline and plane model.",
        "sql": """
            SELECT al.name AS airline, 
                   p.name AS plane, 
                   COUNT(*)::integer AS route_combinations
            FROM routes r1
            JOIN routes r2 ON r1.destination_airport_id = r2.source_airport_id
            JOIN airlines al ON r1.airline_id = al.airline_id
            JOIN planes p ON r1.plane_id = p.plane_id
            WHERE r1.airline_id = r2.airline_id 
              AND r1.plane_id = r2.plane_id
              AND r1.source_airport_id != r2.destination_airport_id
            GROUP BY al.name, p.name
            ORDER BY route_combinations DESC 
            LIMIT 20;
        """,
        "neo4j_A": """
            MATCH (a:Airport)-[r1:HAS_ROUTE]->(b:Airport)-[r2:HAS_ROUTE]->(c:Airport)
            WHERE a <> c 
              AND r1.airline_id = r2.airline_id 
              AND r1.plane_id = r2.plane_id
            MATCH (al:Airline {airline_id: r1.airline_id})
            MATCH (p:Plane {plane_id: r1.plane_id})
            RETURN al.name AS airline, 
                   p.name AS plane, 
                   COUNT(*) AS route_combinations
            ORDER BY route_combinations DESC 
            LIMIT 20;
        """,
        "neo4j_B": """
            MATCH (a:Airport)-[:ROUTE_ORIGIN]->(rt1:Route)-[:ROUTE_DEST]->(b:Airport)-[:ROUTE_ORIGIN]->(rt2:Route)-[:ROUTE_DEST]->(c:Airport)
            WHERE a <> c
            MATCH (rt1)-[:OPERATED_BY]->(al:Airline)<-[:OPERATED_BY]-(rt2)
            MATCH (rt1)-[:USES_PLANE]->(p:Plane)<-[:USES_PLANE]-(rt2)
            RETURN al.name AS airline, 
                   p.name AS plane, 
                   COUNT(*) AS route_combinations
            ORDER BY route_combinations DESC 
            LIMIT 20;
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
        if v_str.isdigit() or (v_str.startswith('-') and v_str[1:].isdigit()):
            return int(v_str)
        try:
            return round(float(v_str), 2)
        except ValueError:
            return v_str
    return str(v).strip()

def normalize_row(row):
    if isinstance(row, dict):
        return [normalize_value(v) for v in row.values()]
    elif isinstance(row, (list, tuple)):
        return [normalize_value(v) for v in row]
    return [normalize_value(row)]

def compute_generic_hash(records):
    if records is None or not records:
        return "EMPTY_RESULT", []
    normalized_data = [normalize_row(r) for r in records]
    normalized_data.sort(key=lambda x: str(x))
    serialized = json.dumps(normalized_data, sort_keys=True)
    return hashlib.sha256(serialized.encode('utf-8')).hexdigest(), normalized_data

def process_query1_map(records):
    if not records:
        return {}
    res_map = {}
    for r in records:
        if isinstance(r, dict):
            o = int(r['origin_airport_id'])
            d = int(r['dest_airport_id'])
            avg_d = float(r['avg_delay']) if r['avg_delay'] is not None else 0.0
            cnt = int(r['flight_cnt'])
        else:
            o = int(r[0])
            d = int(r[1])
            avg_d = float(r[2]) if r[2] is not None else 0.0
            cnt = int(r[3])
        res_map[(o, d)] = (avg_d, cnt)
    return res_map

def verify_query1_tolerant(map_ref, map_target, tolerance=0.2):
    ref_keys = set(map_ref.keys())
    target_keys = set(map_target.keys())
    
    if ref_keys != target_keys:
        return False, f"Mancanza di coppie (Ref={len(ref_keys)}, Target={len(target_keys)})"
        
    for k in ref_keys:
        ref_avg, ref_cnt = map_ref[k]
        target_avg, target_cnt = map_target[k]
        
        if ref_cnt != target_cnt:
            return False, f"Conteggio voli diverso su coppia {k}: Ref={ref_cnt} vs Target={target_cnt}"
            
        if abs(ref_avg - target_avg) > tolerance:
            return False, f"Media fuori tolleranza su coppia {k}: Ref={ref_avg} vs Target={target_avg}"
            
    return True, "OK"

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
    return times, records

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
    return times, records

def run_benchmarks():
    print("="*95)
    print(" INITIALIZING DATABASE CONNECTIONS")
    print("="*95)

    try:
        sql_conn = psycopg2.connect(host=SQL_HOST, port=SQL_PORT, user=SQL_USER, password=SQL_PASSWORD, dbname=SQL_DB)
        print("✅ Connected to PostgreSQL")
    except Exception as e:
        print(f"❌ PostgreSQL Connection Failed: {e}")
        sql_conn = None

    try:
        neo4j_driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        neo4j_driver.verify_connectivity()
        print("✅ Connected to Neo4j")
    except Exception as e:
        print(f"❌ Neo4j Connection Failed: {e}")
        return

    results = []

    print("\n" + "="*95)
    print(" STARTING HEAVY BENCHMARKS WITH EQUIVALENCE CONTROL")
    print("="*95)

    for q_name, q_data in QUERIES.items():
        print(f"\n▶ Executing {q_name}: {q_data['description']}")
        
        # SQL Execution
        sql_failed = False
        if sql_conn:
            try:
                execute_sql(sql_conn, q_data["sql"], WARMUP_RUNS)
                sql_times, sql_records = execute_sql(sql_conn, q_data["sql"], TEST_RUNS)
                sql_avg = statistics.mean(sql_times)
                sql_rows = len(sql_records)
                print(f"   SQL        : {sql_avg:.4f}s | Rows: {sql_rows}")
            except Exception as e:
                print(f"   SQL        : FAILED ({e})")
                sql_avg, sql_rows, sql_records = None, 0, None
                sql_failed = True
                sql_conn.rollback()
        else:
            sql_avg, sql_rows, sql_records = None, 0, None
            sql_failed = True

        # Schema A Execution
        try:
            execute_neo4j(neo4j_driver, NEO4J_DB_A, q_data["neo4j_A"], WARMUP_RUNS)
            neo_a_times, neo_a_records = execute_neo4j(neo4j_driver, NEO4J_DB_A, q_data["neo4j_A"], TEST_RUNS)
            neo_a_avg = statistics.mean(neo_a_times)
            neo_a_rows = len(neo_a_records)
            print(f"   Schema A   : {neo_a_avg:.4f}s | Rows: {neo_a_rows}")
        except Exception as e:
            print(f"   Schema A   : FAILED ({e})")
            neo_a_avg, neo_a_rows, neo_a_records = None, 0, []

        # Schema B Execution
        try:
            execute_neo4j(neo4j_driver, NEO4J_DB_B, q_data["neo4j_B"], WARMUP_RUNS)
            neo_b_times, neo_b_records = execute_neo4j(neo4j_driver, NEO4J_DB_B, q_data["neo4j_B"], TEST_RUNS)
            neo_b_avg = statistics.mean(neo_b_times)
            neo_b_rows = len(neo_b_records)
            print(f"   Schema B   : {neo_b_avg:.4f}s | Rows: {neo_b_rows}")
        except Exception as e:
            print(f"   Schema B   : FAILED ({e})")
            neo_b_avg, neo_b_rows, neo_b_records = None, 0, []

        # HASH CALCULATION
        sql_hash = compute_generic_hash(sql_records)[0] if (not sql_failed and sql_records is not None) else "ERR"
        neo_a_hash, _ = compute_generic_hash(neo_a_records)
        neo_b_hash, _ = compute_generic_hash(neo_b_records)

        hash_str = f"(Hashes: SQL={sql_hash[:8]}, A={neo_a_hash[:8]}, B={neo_b_hash[:8]})"

        # EQUIVALENCE VERIFICATION
        if sql_failed:
            if q_name == "1_Global_Pair_Agg":
                map_a = process_query1_map(neo_a_records)
                map_b = process_query1_map(neo_b_records)
                ok_ab, msg_ab = verify_query1_tolerant(map_a, map_b)
                match_status = "✅ MATCH" if ok_ab else "❌ MISMATCH"
                if not ok_ab:
                    print(f"   [Discrepanza Neo4j Schema A vs Schema B]: {msg_ab}")
            else:
                match_status = "✅ MATCH" if (neo_a_hash == neo_b_hash and neo_a_hash != "EMPTY_RESULT") else "❌ MISMATCH"
            
            print(f"   Equivalence Verification: {match_status} {hash_str} [SQL FALLITO: Confronto Neo4j A vs B]")
        else:
            if q_name == "1_Global_Pair_Agg":
                map_sql = process_query1_map(sql_records)
                map_a = process_query1_map(neo_a_records)
                map_b = process_query1_map(neo_b_records)
                
                ok_a, msg_a = verify_query1_tolerant(map_sql, map_a)
                ok_b, msg_b = verify_query1_tolerant(map_sql, map_b)
                
                if ok_a and ok_b:
                    match_status = "✅ MATCH"
                else:
                    match_status = "❌ MISMATCH"
                    if not ok_a:
                        print(f"   [Discrepanza SQL vs Schema A]: {msg_a}")
                    if not ok_b:
                        print(f"   [Discrepanza SQL vs Schema B]: {msg_b}")
            else:
                match_status = "✅ MATCH" if (sql_hash == neo_a_hash == neo_b_hash) else "❌ MISMATCH"

            print(f"   Equivalence Verification: {match_status} {hash_str}")

        results.append({
            "Query": q_name,
            "SQL": f"{sql_avg:.4f}s" if sql_avg else "ERR",
            "Schema_A": f"{neo_a_avg:.4f}s" if neo_a_avg else "ERR",
            "Schema_B": f"{neo_b_avg:.4f}s" if neo_b_avg else "ERR",
            "Match": match_status
        })

    if sql_conn:
        sql_conn.close()
    neo4j_driver.close()

    print("\n" + "="*95)
    print(f"{'HEAVY BENCHMARK SUMMARY WITH EQUIVALENCE CONTROL':^95}")
    print("="*95)
    print(f"{'Query Name':<28} | {'PostgreSQL':<12} | {'Neo4j Schema A':<14} | {'Neo4j Schema B':<14} | {'Answers':<10}")
    print("-" * 95)
    for r in results:
        print(f"{r['Query']:<28} | {r['SQL']:<12} | {r['Schema_A']:<14} | {r['Schema_B']:<14} | {r['Match']:<10}")
    print("="*95 + "\n")

if __name__ == "__main__":
    run_benchmarks()
    