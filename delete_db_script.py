import os
import time
from sqlalchemy import create_engine, text
from sqlalchemy.exc import OperationalError, SQLAlchemyError

# ==========================================================
# CONFIGURATION / PATH DEFINITIONS
# ==========================================================
DB_USER = os.environ.get('DB_USER', 'admin')
DB_PASSWORD = os.environ.get('DB_PASSWORD', 'supersecretpassword')
DB_HOST = os.environ.get('DB_HOST', 'localhost')
DB_PORT = os.environ.get('DB_PORT', '5432')
TARGET_DB_NAME = 'flightdb'  # The database to drop[cite: 1]

# ==========================================================
# FUNCTION: CONNECT TO POSTGRES & DROP TARGET DATABASE
# ==========================================================
def drop_database(max_retries=5, delay=5):
    print("FUNCTION_1: CONNECT TO SQL SERVER & DROP TARGET DATABASE\n")
    
    # Connect to the default 'postgres' database since you cannot drop a database while connected to it
    base_uri = f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/postgres"
    
    print(f"    Step 1: Attempting connection to PostgreSQL server at {DB_HOST}:{DB_PORT}...")
    
    engine = create_engine(base_uri, isolation_level="AUTOCOMMIT")
    connected = False
    
    for attempt in range(1, max_retries + 1):
        try:
            with engine.connect() as conn:
                connected = True
                print("            ✅ Connected to server successfully\n")
                break
        except OperationalError:
            print(f"            ⏳ Attempt {attempt}/{max_retries} failed. DB server not ready. Retrying in {delay} seconds...")
            time.sleep(delay)
        except SQLAlchemyError as e:
            print(f"            ❌ Connection failed with a fatal error: {e}")
            exit(1)
            
    if not connected:
        print("            ❌ Error: Could not connect to the database microservice after multiple attempts.")
        exit(1)
        
    # Step 2: Check if database exists and drop it (along with all its tables)
    print(f"    Step 2: Checking if database '{TARGET_DB_NAME}' exists...")
    with engine.connect() as conn:
        result = conn.execute(text(f"SELECT 1 FROM pg_database WHERE datname = '{TARGET_DB_NAME}'"))
        exists = result.scalar()
        if exists:
            print(f"    Step 3: Terminating active connections and dropping database '{TARGET_DB_NAME}'...")
            try:
                # FORCE keyword works in PostgreSQL 13+ to drop even if active sessions exist
                conn.execute(text(f"DROP DATABASE {TARGET_DB_NAME} WITH (FORCE)"))
            except Exception:
                # Fallback method to forcefully terminate active connections if FORCE is unsupported
                conn.execute(text(f"""
                    SELECT pg_terminate_backend(pg_stat_activity.pid)
                    FROM pg_stat_activity
                    WHERE pg_stat_activity.datname = '{TARGET_DB_NAME}'
                      AND pid <> pg_backend_pid();
                """))
                conn.execute(text(f"DROP DATABASE {TARGET_DB_NAME}"))
                
            print(f"            ✅ Database '{TARGET_DB_NAME}' and all its tables deleted successfully!\n")
        else:
            print(f"            ℹ️  Database '{TARGET_DB_NAME}' does not exist, nothing to delete.\n")
            
    engine.dispose()

# ==========================================================
# MAIN EXECUTION FLOW
# ==========================================================
if __name__ == '__main__':
    drop_database()
    
    print("\n" + "="*54)
    print("SUCCESS: Database and all tables have been wiped out!")
    print("="*54 + "\n")