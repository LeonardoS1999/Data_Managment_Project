import os
from neo4j import GraphDatabase
from neo4j.exceptions import ServiceUnavailable, ClientError

# ==========================================================
# CONFIGURATION / PATH DEFINITIONS
# ==========================================================
NEO4J_URI = os.environ.get('NEO4J_URI', 'bolt://localhost:7687')
NEO4J_USER = os.environ.get('NEO4J_USER', 'neo4j')
NEO4J_PASSWORD = os.environ.get('NEO4J_PASSWORD', 'Leonardo1846461')
NEO4J_DATABASE_A = os.environ.get('NEO4J_DATABASE', 'flightdbSchemaA')  # Target database to clear
NEO4J_DATABASE_B = os.environ.get('NEO4J_DATABASE', 'flightdbSchemaB')  # Target database to clear

# ==========================================================
# FUNCTION 1: CONNECT TO NEO4J
# ==========================================================
def get_neo4j_driver():
    print("FUNCTION_1: CONNECT TO NEO4J DATABASE\n")
    print(f"    Step 1: Attempting connection to {NEO4J_URI}...")
    try:
        driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        driver.verify_connectivity()
        print("            ✅ Done\n")
        return driver
    except ServiceUnavailable as e:
        print(f"            ❌ Connection failed: {e}")
        exit(1)

# ==========================================================
# FUNCTION 2: CLEAR ALL NODES & RELATIONSHIPS IN TARGET DB
# ==========================================================
def clear_database_data(driver, db_name):
    print(f"FUNCTION_2: CLEARING ALL CONTENTS FROM DATABASE '{db_name}'\n")
    print("    Step 1: Running batched DETACH DELETE...")
    
    # Batched delete query to safely clear large datasets without memory errors
    batched_query = """
    MATCH (n)
    CALL {
        WITH n
        DETACH DELETE n
    } IN TRANSACTIONS OF 10000 ROWS
    """
    
    try:
        with driver.session(database=db_name) as session:
            session.run(batched_query)
            print(f"            ✅ Successfully wiped all data inside '{db_name}'\n")
    except ClientError as e:
        print(f"            ⚠️ Error target database issue: {e}\n")
    except Exception as e:
        # Fallback to standard DETACH DELETE for smaller datasets or older syntax
        print(f"            ⚠️ Batched delete failed ({e}). Attempting fallback DETACH DELETE...")
        try:
            fallback_query = "MATCH (n) DETACH DELETE n"
            with driver.session(database=db_name) as session:
                session.run(fallback_query)
            print(f"            ✅ Done\n")
        except Exception as fallback_err:
            print(f"            ❌ Error clearing database: {fallback_err}\n")

# ==========================================================
# OPTIONAL FUNCTION 3: DROP DATABASE ENTIRELY (ENTERPRISE ONLY)
# ==========================================================
def drop_database_completely(driver, db_name):
    print(f"OPTIONAL: DROPPING DATABASE STRUCTURE '{db_name}' ENTIRELY\n")
    try:
        with driver.session(database="system") as session:
            session.run(f"DROP DATABASE {db_name} IF EXISTS")
            print(f"            ✅ Database '{db_name}' dropped from Neo4j server\n")
    except Exception as e:
        print(f"            ❌ Error dropping database '{db_name}': {e}\n")

# ==========================================================
# MAIN EXECUTION FLOW
# ==========================================================
if __name__ == '__main__':
    driver = get_neo4j_driver()
    
    # Option A: Wipe all nodes & relationships (keeps the 'flightdb' container ready for re-loading)
    #clear_database_data(driver, NEO4J_DATABASE_A)
    #clear_database_data(driver, NEO4J_DATABASE_B)
    
    # Option B: Completely drop the database from Neo4j (Uncomment if you want to delete the whole DB instance)
    drop_database_completely(driver, NEO4J_DATABASE_A)

    print("\n" + "="*54)
    print(f"SUCCESS: Cleaning operations finished for '{NEO4J_DATABASE_A}'!")
    print("="*54 + "\n")

    driver.close()


    driver = get_neo4j_driver()

    drop_database_completely(driver, NEO4J_DATABASE_B)
    
    print("\n" + "="*54)
    print(f"SUCCESS: Cleaning operations finished for '{NEO4J_DATABASE_B}'!")
    print("="*54 + "\n")


    driver.close()
    
    