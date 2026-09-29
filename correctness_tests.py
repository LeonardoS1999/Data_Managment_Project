import os
import sys
import pandas as pd
from pathlib import Path

DATA_DIR = Path('DATA_USED')

def test_column_lowercasing():
    print("    Step 1: --- Testing Column Lowercasing ---")
    csv_files = list(DATA_DIR.glob('*.csv'))
    assert csv_files, "No CSV files found in DATA_USED to test."
    
    all_passed = True
    for file_path in csv_files:
        df = pd.read_csv(file_path, nrows=1)
        non_lower = [col for col in df.columns if col != col.lower().strip()]
        if non_lower:
            print(f"            ❌ Failed: {file_path.name} contains non-lowercase/unstripped columns: {non_lower}")
            all_passed = False
        else:
            print(f"            ✅ Passed: {file_path.name} (all {len(df.columns)} columns are lowercase)")
    
    assert all_passed, "Column lowercasing verification failed."

def test_primary_key_uniqueness():
    print("\n    Step 2: --- Testing Primary Key Uniqueness ---")
    
    # Mapping of tables to their primary key ID column names
    pk_mapping = {
        'countries.csv': 'country_id',
        'merged_airports.csv': 'airport_id',
        'airlines.csv': 'airline_id',
        'planes.csv': 'plane_id',
        'routes.csv': 'route_id',
        'merged_flights_cleaned.csv': 'flight_id'
    }

    all_passed = True

    for filename, pk_col in pk_mapping.items():
        file_path = DATA_DIR / filename
        if not file_path.exists():
            print(f"            ⚠️ Skipped [{filename}]: File not found.")
            continue

        df = pd.read_csv(file_path, low_memory=False)
        df.columns = df.columns.str.lower().str.strip()

        # Fallback to auto-detect any ID column if exact mapped name is not present
        if pk_col not in df.columns:
            possible_pks = [c for c in df.columns if c == 'id' or c.endswith('_id')]
            if possible_pks:
                pk_col = possible_pks[0]
            else:
                print(f"            ⚠️ Skipped [{filename}]: Primary key column '{pk_col}' missing.")
                continue

        # Extract non-null/valid string IDs
        series = df[pk_col].dropna().astype(str).str.strip()
        valid_ids = series[~series.isin(['\\N', 'nan', '', 'None', 'null'])]

        num_duplicates = valid_ids.duplicated().sum()
        if num_duplicates > 0:
            print(f"            ❌ Failed [{filename}]: Found {num_duplicates} duplicate ID values in column '{pk_col}'.")
            all_passed = False
        else:
            print(f"            ✅ Passed [{filename}]: Primary key '{pk_col}' values are strictly unique across {len(valid_ids)} records.")

    assert all_passed, "Primary key uniqueness verification failed."

def test_foreign_key_referencing():
    print("\n    Step 3: --- Testing Foreign Key Referencing ---")
    
    def load_table(filename):
        p = DATA_DIR / filename
        if not p.exists():
            return None
        df = pd.read_csv(p, low_memory=False)
        df.columns = df.columns.str.lower().str.strip()
        return df

    countries = load_table('countries.csv')
    airports = load_table('merged_airports.csv')
    airlines = load_table('airlines.csv')
    planes = load_table('planes.csv')
    routes = load_table('routes.csv')
    flights = load_table('merged_flights_cleaned.csv')

    all_passed = True

    def verify_fk(child_df, child_col, parent_df, parent_col, label):
        nonlocal all_passed
        if child_df is None or parent_df is None:
            print(f"            ⚠️ Skipped [{label}]: Required dataset missing.")
            return
        if child_col not in child_df.columns or parent_col not in parent_df.columns:
            print(f"            ⚠️ Skipped [{label}]: Key column missing ('{child_col}' or '{parent_col}').")
            return

        def clean_key_set(series):
            keys = set()
            for val in series.dropna():
                val_str = str(val).strip()
                if val_str.lower() in {'\\N', 'nan', '', 'none', '<na>'}:
                    continue
                # Remove trailing .0 caused by pandas float casting of integer IDs with nulls
                if val_str.endswith('.0'):
                    val_str = val_str[:-2]
                keys.add(val_str)
            return keys

        parent_keys = clean_key_set(parent_df[parent_col])
        child_keys = clean_key_set(child_df[child_col])

        orphans = child_keys - parent_keys
        if orphans:
            print(f"            ❌ Failed [{label}]: {len(orphans)} orphan keys found in '{child_col}' not present in '{parent_col}' (Sample: {list(orphans)[:5]})")
            all_passed = False
        else:
            print(f"            ✅ Passed [{label}]: All foreign keys in '{child_col}' correctly match '{parent_col}'")

    verify_fk(airports, 'country_id', countries, 'country_id', "Airports -> Countries")
    verify_fk(airlines, 'country_id', countries, 'country_id', "Airlines -> Countries")
    verify_fk(routes, 'plane_id', planes, 'plane_id', "Routes -> Planes")
    verify_fk(flights, 'airline_id', airlines, 'airline_id', "Flights -> Airlines")
    verify_fk(flights, 'route_id', routes, 'route_id', "FLights -> route_id")
    verify_fk(flights, 'origin_airport_id', airports, 'airport_id', "Flights -> Origin Airport")
    verify_fk(flights, 'dest_airport_id', airports, 'airport_id', "Flights -> Destination Airport")

    assert all_passed, "Foreign key join verification failed."

def test_raw_to_cleaned_mapping_reconciliation():
    print("\n    Step 4: --- Testing Raw Code Lookup Reconciliation ---")
    
    flights_cleaned_path = DATA_DIR / 'merged_flights_cleaned.csv'
    airports_path = DATA_DIR / 'merged_airports.csv'
    airlines_path = DATA_DIR / 'airlines.csv'
    
    if not flights_cleaned_path.exists():
        print("            ⚠️ Skipped: merged_flights_cleaned.csv not found.")
        return

    cleaned_df = pd.read_csv(flights_cleaned_path, low_memory=False)
    airports_df = pd.read_csv(airports_path, low_memory=False)
    airlines_df = pd.read_csv(airlines_path, low_memory=False)
    
    airports_df.columns = airports_df.columns.str.lower().str.strip()
    airlines_df.columns = airlines_df.columns.str.lower().str.strip()
    
    airport_code_col = next((c for c in airports_df.columns if c == 'iata' or 'iata' in c), 'iata')
    airport_id_col = next((c for c in airports_df.columns if 'airport_id' in c or c == 'id'), 'airport_id')
    
    airline_code_col = next((c for c in airlines_df.columns if 'iata' in c or 'code' in c), 'iata')
    airline_id_col = next((c for c in airlines_df.columns if 'airline_id' in c or c == 'id'), 'airline_id')

    # 1. Clean codes and deduplicate keeping the FIRST occurrence (Mirrors ETL pipeline)
    airports_df[airport_code_col] = airports_df[airport_code_col].astype(str).str.strip().str.upper()
    airlines_df[airline_code_col] = airlines_df[airline_code_col].astype(str).str.strip().str.upper()
    
    airports_deduped = airports_df.drop_duplicates(subset=[airport_code_col])
    airlines_deduped = airlines_df.drop_duplicates(subset=[airline_code_col])

    # 2. Map original string codes to expected database IDs based on deduplicated sets
    airport_map = airports_deduped.set_index(airport_code_col)[airport_id_col].to_dict()
    airline_map = airlines_deduped.set_index(airline_code_col)[airline_id_col].to_dict()

    all_passed = True
    
    # Configuration for source flight files
    raw_files_config = [
        ('flights_2013.csv', {'origin': 'origin', 'dest': 'dest', 'airline': 'carrier'}),
        ('flights_2015.csv', {'origin': 'origin_airport', 'dest': 'destination_airport', 'airline': 'airline'})
    ]

    offset = 0
    for raw_filename, col_map in raw_files_config:
        raw_path = DATA_DIR / raw_filename
        if not raw_path.exists():
            print(f"            ⚠️ Skipped reconciliation for {raw_filename}: raw file not found.")
            continue

        print(f"            Reconciling raw source file: {raw_filename}...")
        raw_df = pd.read_csv(raw_path, low_memory=False)
        raw_df.columns = raw_df.columns.str.lower().str.strip()
        
        num_rows = len(raw_df)
        sub_cleaned = cleaned_df.iloc[offset : offset + num_rows].reset_index(drop=True)
        offset += num_rows

        # Helper to safely compare numeric IDs, ignoring float representation artifacts
        def check_mismatches(raw_codes_series, map_dict, assigned_ids_series):
            raw_codes = raw_codes_series.astype(str).str.strip().str.upper()
            expected_ids = pd.to_numeric(raw_codes.map(map_dict), errors='coerce')
            actual_ids = pd.to_numeric(assigned_ids_series, errors='coerce')
            return (expected_ids.notna()) & (expected_ids != actual_ids)

        # 1. Verify Origin Airport Code Lookup
        origin_mismatches = check_mismatches(raw_df[col_map['origin']], airport_map, sub_cleaned['origin_airport_id'])
        if origin_mismatches.any():
            print(f"            ❌ Failed [{raw_filename} Origin Airport]: {origin_mismatches.sum()} mismatches.")
            all_passed = False
        else:
            print(f"            ✅ Passed [{raw_filename} Origin Airport]")

        # 2. Verify Destination Airport Code Lookup
        dest_mismatches = check_mismatches(raw_df[col_map['dest']], airport_map, sub_cleaned['dest_airport_id'])
        if dest_mismatches.any():
            print(f"            ❌ Failed [{raw_filename} Destination Airport]: {dest_mismatches.sum()} mismatches.")
            all_passed = False
        else:
            print(f"            ✅ Passed [{raw_filename} Destination Airport]")

        # 3. Verify Airline Code Lookup
        airline_mismatches = check_mismatches(raw_df[col_map['airline']], airline_map, sub_cleaned['airline_id'])
        if airline_mismatches.any():
            print(f"            ❌ Failed [{raw_filename} Airline]: {airline_mismatches.sum()} mismatches.")
            all_passed = False
        else:
            print(f"            ✅ Passed [{raw_filename} Airline]")

    assert all_passed, "Raw source code reconciliation test failed."

if __name__ == '__main__':
    try:
        test_column_lowercasing()
        test_primary_key_uniqueness()
        test_foreign_key_referencing()
        test_raw_to_cleaned_mapping_reconciliation()

    except Exception as e:
        print(f"\n❌ SUITE FAILED: {e}")
        sys.exit(1)