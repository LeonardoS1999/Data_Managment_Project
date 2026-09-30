import pandas as pd
import numpy as np
import os
import csv
import re
import subprocess
import time
import unicodedata
from pathlib import Path
from difflib import SequenceMatcher

# ==========================================================
# CONFIGURATION / PATH DEFINITIONS
# ==========================================================
DATA_DIR = 'DATA_USED'
COUNTRIES_PATH = os.path.join(DATA_DIR, 'countries.csv')
PLANES_PATH = os.path.join(DATA_DIR, 'planes.csv')
ROUTES_PATH = os.path.join(DATA_DIR, 'routes.csv')
AIRLINES_PATH = os.path.join(DATA_DIR, 'airlines.csv')
AIRPORTS_PATH = os.path.join(DATA_DIR, 'airports.csv')
MERGED_AIRPORTS_PATH = os.path.join(DATA_DIR, 'merged_airports.csv')
FLIGHTS_PATH = os.path.join(DATA_DIR, 'merged_flights.csv')
FLIGHTS_CLEANED_PATH = os.path.join(DATA_DIR, 'merged_flights_cleaned.csv')
DAFIF_PATH = os.path.join(DATA_DIR, 'airports-dafif.csv')
FLIGHTS_2013 = os.path.join(DATA_DIR, 'flights_2013.csv')
FLIGHTS_2015 = os.path.join(DATA_DIR, 'flights_2015.csv')

# ==========================================================
# COLUMN FORMATTING STEP
# ==========================================================
def standardize_column_names(df: pd.DataFrame) -> pd.DataFrame:
    """Replaces spaces with underscores, strips quotes/apostrophes, and converts to lowercase safely."""
    df.columns = (
        df.columns.str.strip()
        .str.replace(r"['\"’`]", "", regex=True)
        .str.replace(r'\s+', '_', regex=True)
        .str.lower()
    )
    return df

# ==========================================================
# FUNCTION 1: CLEAN AND MERGE AIRPORTS
# ==========================================================
def clean_and_merge_airports():
    func_start = time.time()
    print("FUNCTION_1: CLEAN AND MERGE AIRPORTS\n")
    
    print("    Step 1: Parsing and fixing countries.csv safely...")
    step_start = time.time()
    countries_data = []
    with open(COUNTRIES_PATH, 'r', encoding='utf-8') as f:
        header = f.readline()
        for line in f:
            line_str = line.strip()
            if not line_str:
                continue
            parts = [p.strip() for p in line_str.split(';') if p.strip() != '']
            
            if len(parts) >= 3:
                name = ", ".join(parts[:-2])
                iso_code = parts[-2]
                dafif_code = parts[-1]
                countries_data.append([name, iso_code, dafif_code])
            elif len(parts) == 2:
                countries_data.append([parts[0], parts[1], np.nan])
            elif len(parts) == 1:
                countries_data.append([parts[0], np.nan, np.nan])
    
    df_countries = pd.DataFrame(countries_data, columns=['name', 'iso_code', 'dafif_code'])
    
    df_countries_clean = (
        df_countries
        .dropna(subset=['dafif_code'])
        .drop_duplicates(subset=['dafif_code'], keep='first')
    )
    country_map = dict(
        zip(
            df_countries_clean['dafif_code'].astype(str).str.strip(), 
            df_countries_clean['name']
        )
    )
    print(f"            ✅ Done in {time.time() - step_start:.4f} seconds\n")

    print("    Step 2: Loading civilian airports.csv...")
    step_start = time.time()
    df_orig = pd.read_csv(AIRPORTS_PATH, sep=None, engine='python')
    df_orig = standardize_column_names(df_orig)
    
    icao_col = next((c for c in df_orig.columns if 'icao' in c or c == 'ident'), None)
    if not icao_col:
        raise KeyError(f"            ❌ Could not find an ICAO column in {AIRPORTS_PATH}. Available columns: {list(df_orig.columns)}")
    
    df_orig['icao'] = df_orig[icao_col].astype(str).str.strip()
    print(f"            ✅ Done in {time.time() - step_start:.4f} seconds\n")

    print("    Step 3: Loading airports-dafif.csv...")
    step_start = time.time()
    df_dafif = pd.read_csv(DAFIF_PATH, sep=None, engine='python', header=None)
    df_dafif.columns = ['dafif_country', 'name', 'icao', 'iata', 'longitude', 'latitude', 'elevation']
    df_dafif['icao'] = df_dafif['icao'].astype(str).str.strip()
    df_dafif['dafif_country'] = df_dafif['dafif_country'].astype(str).str.strip()
    print(f"            ✅ Done in {time.time() - step_start:.4f} seconds\n")

    print("    Step 4: Analyzing differences and building the is_dafif property...")
    step_start = time.time()
    dafif_icaos = set(df_dafif['icao'])
    orig_icaos = set(df_orig['icao'])

    df_orig['is_dafif'] = df_orig['icao'].isin(dafif_icaos)
    df_dafif_new = df_dafif[~df_dafif['icao'].isin(orig_icaos)].copy()
    print(f"            ✅ Done in {time.time() - step_start:.4f} seconds\n")

    print("    Step 5: Structuring and normalizing new DAFIF airfields...")
    step_start = time.time()
    airport_id_col = next((c for c in df_orig.columns if 'airport_id' in c or c == 'id'), None)
    max_id = df_orig[airport_id_col].max() if airport_id_col else len(df_orig)
    df_dafif_new['airport_id'] = range(max_id + 1, max_id + 1 + len(df_dafif_new))

    df_dafif_new['state'] = df_dafif_new['dafif_country'].map(country_map)
    df_dafif_new['city'] = np.nan
    df_dafif_new['iata'] = df_dafif_new['iata'].replace('\\N', np.nan)
    df_dafif_new['high(feet)'] = df_dafif_new['elevation']
    df_dafif_new['timezone'] = np.nan
    df_dafif_new['ora_legale'] = np.nan
    df_dafif_new['tz_database_timezone'] = np.nan
    df_dafif_new['type'] = 'airport'
    df_dafif_new['source'] = 'DAFIF'
    df_dafif_new['is_dafif'] = True
    print(f"            ✅ Done in {time.time() - step_start:.4f} seconds\n")

    print("    Step 6: Harmonizing column structures and merging...")
    step_start = time.time()
    columns_template = [
        'airport_id', 'name', 'city', 'state', 'iata', 'icao', 
        'latitude', 'longitude', 'high(feet)', 'timezone', 
        'ora_legale', 'tz_database_timezone', 'type', 'source', 'is_dafif'
    ]

    for col in columns_template:
        if col not in df_orig.columns:
            df_orig[col] = np.nan

    df_orig_aligned = df_orig[columns_template]
    df_dafif_new_aligned = df_dafif_new[columns_template]
    df_merged = pd.concat([df_orig_aligned, df_dafif_new_aligned], ignore_index=True)
    print(f"            ✅ Done in {time.time() - step_start:.4f} seconds\n")

    print("    Step 7: Lowercasing column titles and replacing spaces with underscores...")
    step_start = time.time()
    df_merged = standardize_column_names(df_merged)
    print(f"            ✅ Done in {time.time() - step_start:.4f} seconds\n")

    print("    Step 8: Deleting 'type' and 'source' columns...")
    step_start = time.time()
    df_merged = df_merged.drop(columns=['type', 'source'], errors='ignore')
    print(f"            ✅ Done in {time.time() - step_start:.4f} seconds\n")

    print("    Step 9: Saving master file to disk...")
    step_start = time.time()
    df_merged.to_csv(MERGED_AIRPORTS_PATH, sep=',', index=False)
    print(f"            ✅ Done in {time.time() - step_start:.4f} seconds\n")

    print("\n" + "="*77)
    print(f"SUCCESS: Airport cleaning and merging completed, executed in {time.time() - func_start:.4f} seconds")
    print(f"-> Base civilian records: {len(df_orig)}")
    print(f"-> Unmatched DAFIF additions: {len(df_dafif_new)}")
    print(f"-> Final row count in merged_airports.csv: {len(df_merged)}")
    print("="*77 + "\n")

# ==========================================================
# FUNCTION 2: MERGE FLIGHTS (2013 + 2015)
# ==========================================================
def merge_flights():
    func_start = time.time()
    print("FUNCTION_2: MERGE FLIGHTS\n")
    
    print("    Step 1: Loading data with universal separator detection...")
    step_start = time.time()
    df_2013 = pd.read_csv(FLIGHTS_2013, sep=None, engine='python')
    df_2015 = pd.read_csv(FLIGHTS_2015, sep=None, engine='python') 
    
    df_2013 = standardize_column_names(df_2013)
    df_2015 = standardize_column_names(df_2015)
    print(f"            ✅ Done in {time.time() - step_start:.4f} seconds\n")

    print("    Step 2: Defining standard unified database schema...")
    step_start = time.time()
    mapping_2013 = {
        'year': 'year', 'month': 'month', 'day': 'day',
        'dep_time': 'dep_time', 'sched_dep_time': 'sched_dep_time', 'dep_delay': 'dep_delay',
        'arr_time': 'arr_time', 'sched_arr_time': 'sched_arr_time', 'arr_delay': 'arr_delay',
        'carrier': 'airline_code', 'flight': 'flight_number', 'tailnum': 'tail_number',
        'origin': 'origin_airport', 'dest': 'destination_airport', 'air_time': 'air_time',
        'distance': 'distance', 'id': 'id_2013', 'hour': 'sched_hour', 'minute': 'sched_minute',
        'time_hour': 'time_hour_str', 'name': 'airline_name'
    }

    mapping_2015 = {
        'year': 'year', 'month': 'month', 'day': 'day', 'day_of_week': 'day_of_week',
        'airline': 'airline_code', 'flight_number': 'flight_number', 'tail_number': 'tail_number',
        'origin_airport': 'origin_airport', 'destination_airport': 'destination_airport',
        'scheduled_departure': 'sched_dep_time', 'departure_time': 'dep_time', 'departure_delay': 'dep_delay',
        'taxi_out': 'taxi_out', 'wheels_off': 'wheels_off', 'scheduled_time': 'sched_time_elapsed',
        'elapsed_time': 'actual_time_elapsed', 'air_time': 'air_time', 'distance': 'distance',
        'wheels_on': 'wheels_on', 'taxi_in': 'taxi_in', 'scheduled_arrival': 'sched_arr_time',
        'arrival_time': 'arr_time', 'arrival_delay': 'arr_delay', 'diverted': 'diverted',
        'cancelled': 'cancelled', 'cancellation_reason': 'cancellation_reason',
        'air_system_delay': 'air_system_delay', 'security_delay': 'security_delay',
        'airline_delay': 'airline_delay', 'late_aircraft_delay': 'late_aircraft_delay',
        'weather_delay': 'weather_delay'
    }
    print(f"            ✅ Done in {time.time() - step_start:.4f} seconds\n")

    print("    Step 3: Renaming and aligning column structures...")
    step_start = time.time()
    df1_renamed = df_2013.rename(columns=mapping_2013)
    df2_renamed = df_2015.rename(columns=mapping_2015)
    print(f"            ✅ Done in {time.time() - step_start:.4f} seconds\n")

    print("    Step 4: Standardizing data formats and types...")
    step_start = time.time()
    for df in [df1_renamed, df2_renamed]:
        df['airline_code'] = df['airline_code'].astype(str).str.strip().str.upper()
        df['origin_airport'] = df['origin_airport'].astype(str).str.strip().str.upper()
        df['destination_airport'] = df['destination_airport'].astype(str).str.strip().str.upper()
        df['tail_number'] = df['tail_number'].astype(str).str.strip().str.upper()
    print(f"            ✅ Done in {time.time() - step_start:.4f} seconds\n")

    print("    Step 5: Merging datasets into a single database-ready file...")
    step_start = time.time()
    unified_df = pd.concat([df1_renamed, df2_renamed], ignore_index=True)
    print(f"            ✅ Done in {time.time() - step_start:.4f} seconds\n")

    print("    Step 6: Saving unified CSV file...")
    step_start = time.time()
    unified_df.to_csv(FLIGHTS_PATH, sep=',', index=False)
    print(f"            ✅ Done in {time.time() - step_start:.4f} seconds\n")

    print("\n" + "="*90)
    print(f"SUCCESS: Final file 'merged_flights.csv' has been generated, executed in {time.time() - func_start:.4f} seconds")
    print(f"-> Total Rows Processed: {len(unified_df)}")
    print("="*90 + "\n")


# ==========================================================
# FUNCTION 3: RELATIONAL ADJUSTMENTS & COUNTRY MAPPING
# ==========================================================
def step_0_standardize_separators(data_dir: str) -> None:
    print("    Step 0: Standardizing all CSV files to use comma (',') separators...")
    step_start = time.time()
    
    if not os.path.exists(data_dir):
        print(f"            ❌ Error: Directory '{data_dir}' not found.")
        return

    file_names = [f for f in os.listdir(data_dir) if f.lower().endswith('.csv')]
    
    if not file_names:
        print(f"            ⚠️ Warning: No CSV files found in {data_dir}.")
        return

    for file_name in file_names:
        file_path = os.path.join(data_dir, file_name)
        try:
            df = pd.read_csv(file_path, sep=None, engine='python', encoding='utf-8')
            df = standardize_column_names(df)
            df.to_csv(file_path, sep=',', index=False, encoding='utf-8')
            print(f"            ✅ Standardized separator to ',' for: {file_name}")
        except Exception as e:
            print(f"            ❌ Error standardizing {file_name}: {e}")
            
    print(f"            ✅ Done in {time.time() - step_start:.4f} seconds\n")

def step_1_process_countries(path: str) -> pd.DataFrame:
    print("    Step 1: Processing countries.csv...")
    step_start = time.time()
    if not os.path.exists(path):
        print(f"            ❌ Error: {path} not found!")
        return pd.DataFrame()

    df_countries = pd.read_csv(path, sep=None, engine='python')
    df_countries = standardize_column_names(df_countries)

    name_col = next((c for c in df_countries.columns if 'name' in c), None)
    if name_col:
        df_countries[name_col] = df_countries[name_col].astype(str).str.replace(r'^[0-9,\s]+', '', regex=True)

    id_col = next((c for c in df_countries.columns if c == 'country_id'), None)
    if not id_col:
        df_countries.insert(0, 'country_id', range(1, len(df_countries) + 1))
    else:
        df_countries[id_col] = range(1, len(df_countries) + 1)
    
    df_countries.to_csv(path, sep=',', index=False)
    print(f"            ✅ countries.csv updated and cleaned. Total rows: {len(df_countries)} (Done in {time.time() - step_start:.4f} seconds)\n")
    return df_countries

def step_2_process_planes(path: str) -> pd.DataFrame:
    print("    Step 2: Processing planes.csv...")
    step_start = time.time()
    if not os.path.exists(path):
        print(f"            ❌ Error: {path} not found!")
        return pd.DataFrame()

    df_planes = pd.read_csv(path, sep=None, engine='python')
    df_planes = standardize_column_names(df_planes)
    
    if 'plane_id' not in df_planes.columns:
        df_planes.insert(0, 'plane_id', range(1, len(df_planes) + 1))
    
    df_planes.to_csv(path, sep=',', index=False)
    print(f"            ✅ planes.csv updated with 'plane_id'. Total rows: {len(df_planes)} (Done in {time.time() - step_start:.4f} seconds)\n")
    return df_planes

def step_3_process_routes(path: str, df_planes: pd.DataFrame) -> pd.DataFrame:
    print("    Step 3: Processing routes.csv...")
    step_start = time.time()
    if not os.path.exists(path):
        print(f"            ❌ Error: {path} not found!")
        return pd.DataFrame()

    df_routes = pd.read_csv(path, sep=None, engine='python')
    df_routes = standardize_column_names(df_routes)

    equip_col = next((c for c in df_routes.columns if c.startswith('eq')), None)
    if equip_col and equip_col != 'equipment':
        df_routes.rename(columns={equip_col: 'equipment'}, inplace=True)
        equip_col = 'equipment'


    columns_to_drop = [col for col in df_routes.columns if col in ['codeshare', 'stops']]
    df_routes.drop(columns=columns_to_drop, inplace=True, errors='ignore')

    unmapped_code_counter = 0
    if df_planes is not None and not df_planes.empty:
        df_planes_clean = df_planes.copy()
        df_planes_clean = standardize_column_names(df_planes_clean)

        iata_col = next((c for c in df_planes_clean.columns if 'iata' in c), None)
        icao_col = next((c for c in df_planes_clean.columns if 'icao' in c), None)
        plane_id_col = next((c for c in df_planes_clean.columns if c in ['plane_id', 'id', 'planeid', 'id_plane']), None)

        def clean_code(val):
            if pd.isna(val) or str(val).strip() in ['\\N', '', 'nan', 'None']:
                return None
            val_str = str(val).strip().upper()
            if val_str.endswith('.0'):
                val_str = val_str[:-2]
            return val_str

        def clean_id(val):
            if pd.isna(val) or str(val).strip() in ['\\N', '', 'nan', 'None']:
                return None
            try:
                return str(int(float(val)))
            except (ValueError, TypeError):
                return str(val).strip()

        iata_to_plane_id = {}
        icao_to_plane_id = {}

        if plane_id_col:
            if iata_col:
                for code, pid in zip(df_planes_clean[iata_col], df_planes_clean[plane_id_col]):
                    c_str, p_id = clean_code(code), clean_id(pid)
                    if c_str and p_id:
                        iata_to_plane_id[c_str] = p_id
            if icao_col:
                for code, pid in zip(df_planes_clean[icao_col], df_planes_clean[plane_id_col]):
                    c_str, p_id = clean_code(code), clean_id(pid)
                    if c_str and p_id:
                        icao_to_plane_id[c_str] = p_id

        def process_equipment_pairs(equip_string):
            nonlocal unmapped_code_counter
            if pd.isna(equip_string) or str(equip_string).strip() in ['\\N', '']:
                unmapped_code_counter += 1
                return [(np.nan, np.nan)]
            
            aircraft_codes = [c for c in re.split(r'[\s,/]+', str(equip_string)) if c]
            pairs = []
            for code in aircraft_codes:
                code_clean = clean_code(code)
                if code_clean and code_clean in iata_to_plane_id:
                    pairs.append((code_clean, iata_to_plane_id[code_clean]))
                elif code_clean and code_clean in icao_to_plane_id:
                    pairs.append((code_clean, icao_to_plane_id[code_clean]))
                else:
                    pairs.append((np.nan, np.nan))
                    unmapped_code_counter += 1
            return pairs if pairs else [(np.nan, np.nan)]

        if equip_col:
            pairs_series = df_routes[equip_col].apply(process_equipment_pairs)
            df_routes['_equip_pairs'] = pairs_series
            
            df_routes = df_routes.explode('_equip_pairs').reset_index(drop=True)
            
            df_routes[equip_col] = df_routes['_equip_pairs'].apply(lambda x: x[0])
            mapped_plane_ids = df_routes['_equip_pairs'].apply(lambda x: x[1])
            df_routes.drop(columns=['_equip_pairs'], inplace=True)

            if 'plane_id' in df_routes.columns:
                df_routes.drop(columns=['plane_id'], inplace=True)

            equip_idx = df_routes.columns.get_loc(equip_col) + 1
            df_routes.insert(equip_idx, 'plane_id', mapped_plane_ids)

    if 'route_id' in df_routes.columns:
        df_routes.drop(columns=['route_id'], inplace=True)
    df_routes.insert(0, 'route_id', range(1, len(df_routes) + 1))

    df_routes.to_csv(path, sep=',', index=False)
    print(f"            ✅ routes.csv successfully processed. Final row count: {len(df_routes)} (Done in {time.time() - step_start:.4f} seconds)\n")
    return df_routes

def normalize_country_str(text: str) -> str:
    """Converts unicode diacritics to ASCII, lowercases, and strips punctuation."""
    if pd.isna(text) or str(text).strip() in ['\\N', '', 'nan', 'None']:
        return ""
    text = unicodedata.normalize('NFD', str(text)).encode('ascii', 'ignore').decode('utf-8')
    text = text.lower()
    text = re.sub(r'^[0-9,\s]+', '', text)
    text = re.sub(r'[^a-z0-9\s]', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()

def step_4_map_country_ids(df_countries: pd.DataFrame, airports_path: str, airlines_path: str):
    print("    Step 4: Mapping country_id foreign keys to Airports and Airlines with flexible matching...")
    step_start = time.time()
    
    if df_countries.empty:
        print("            ⚠️ Warning: Countries dataset is empty. Skipping country mapping.")
        return

    name_col = next((c for c in df_countries.columns if 'name' in c), None)
    country_id_col = next((c for c in df_countries.columns if 'country_id' in c), None)
    iso_col = next((c for c in df_countries.columns if 'iso' in c), None)
    dafif_col = next((c for c in df_countries.columns if 'dafif' in c), None)

    country_map = {}

    if name_col and country_id_col:
        for _, row in df_countries.iterrows():
            cid = row[country_id_col]
            raw_name = str(row[name_col])
            c_clean = normalize_country_str(raw_name)
            if c_clean:
                country_map[c_clean] = cid

            if iso_col and pd.notna(row[iso_col]):
                iso_val = normalize_country_str(row[iso_col])
                if iso_val:
                    country_map[iso_val] = cid

            if dafif_col and pd.notna(row[dafif_col]):
                dafif_val = normalize_country_str(row[dafif_col])
                if dafif_val:
                    country_map[dafif_val] = cid

    aliases = {
        "s a": "saudi arabia",
        "alaska": "united states",
        "avianca": "colombia",
        "brunei": "brunei darussalam",
        "canadian territories": "canada",
        "cape verde": "cabo verde",
        "congo (kinshasa)": "dr congo",
        "congo kinshasa": "dr congo",
        "dragon": "hong kong",
        "democratic people's republic of korea": "north korea",
        "democratic peoples republic of korea": "north korea",
        "hong kong sar of china": "hong kong",
        "ivory coast": "cote d ivoire",
        "kyrgyzstan": "kyrgyz republic",
        "lao peoples democratic republic": "laos",
        "russian federation": "russia",
        "syrian arab republic": "syria",
        "usa": "united states",
        "united states of america": "united states",
        "us": "united states",
        "uk": "united kingdom",
        "great britain": "united kingdom",
        "south korea": "south korea",
        "republic of korea": "south korea",
        "korea south": "south korea",
        "north korea": "north korea",
        "vietnam": "viet nam",
        "cote divoire": "cote d ivoire",
        "cote d ivoire": "cote d ivoire",
        "dr congo": "dr congo",
        "congo brazzaville": "congo republic",
        "republic of the congo": "congo republic",
        "burma": "myanmar",
        "czechia": "czech republic",
        "east timor": "timor leste",
        "laos": "laos",
        "syria": "syria",
        "iran": "iran islamic republic of",
        "bolivia": "bolivia plurinational state of",
        "tanzania": "tanzania united republic of",
        "swaziland": "eswatini",
        "taiwan": "taiwan province of china",
        "virgin islands": "united states virgin islands",
        "us virgin islands": "united states virgin islands",
        "u s virgin islands": "united states virgin islands",
    }

    for alias, canonical_name in aliases.items():
        canonical_clean = normalize_country_str(canonical_name)
        alias_clean = normalize_country_str(alias)
        if canonical_clean in country_map:
            country_map[alias_clean] = country_map[canonical_clean]

    stopwords = {
        "republic", "island", "islands", "of", "the", "democratic", 
        "federated", "states", "state", "kingdom", "united", "union", 
        "st", "saint", "south", "north"
    }

    country_tokens_map = {}
    for c_name, cid in country_map.items():
        tokens = set(c_name.split()) - stopwords
        if tokens:
            country_tokens_map[c_name] = (tokens, cid)

    def find_flexible_country_id(country_val):
        val_clean = normalize_country_str(country_val)
        if not val_clean:
            return np.nan

        if val_clean in country_map:
            return country_map[val_clean]

        val_tokens = set(val_clean.split()) - stopwords
        if val_tokens:
            for c_name, (c_tokens, cid) in country_tokens_map.items():
                if val_tokens == c_tokens:
                    return cid

        best_match_id = np.nan
        best_ratio = 0.85

        for c_name, cid in country_map.items():
            if abs(len(c_name) - len(val_clean)) > 5:
                continue
            ratio = SequenceMatcher(None, val_clean, c_name).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_match_id = cid

        return best_match_id

    def map_file(file_path, target_name):
        if not os.path.exists(file_path):
            print(f"            ⚠️ Warning: File '{file_path}' not found. Skipping {target_name} mapping.")
            return

        df = pd.read_csv(file_path, sep=None, engine='python')
        df = standardize_column_names(df)
        
        df.columns = [c.replace(';', '').strip() for c in df.columns]
        if 'country_id' in df.columns:
            df = df.loc[:, ~df.columns.duplicated(keep='first')]

        country_col = next((c for c in df.columns if any(term in c for term in ['state', 'country'])), None)
        
        if country_col:
            mapped_ids = df[country_col].apply(find_flexible_country_id)
            
            if 'country_id' in df.columns:
                df['country_id'] = mapped_ids
            else:
                idx = df.columns.get_loc(country_col) + 1
                df.insert(idx, 'country_id', mapped_ids)
                
            df.to_csv(file_path, sep=',', index=False)
            
            matched_count = mapped_ids.notna().sum()
            total_count = len(mapped_ids)
            print(f"            ✅ Country IDs mapped into {target_name}: {matched_count}/{total_count} successfully matched.")
        else:
            print(f"            ⚠️ Warning: Could not find a country column in {target_name}. Columns found: {list(df.columns)}")

    map_file(airports_path, "Airports")
    map_file(airlines_path, "Airlines")
    print(f"            ✅ Done in {time.time() - step_start:.4f} seconds\n")

# ==========================================================
# FUNCTION 4: FLIGHTS CLEANING & FOREIGN KEY ETL PIPELINE
# ==========================================================
def generate_flight_id(df: pd.DataFrame) -> pd.DataFrame:
    print("    Step 8: generate_flight_id (Finalizing Primary Keys)")
    step_start = time.time()
    
    cols_to_drop = [c for c in ['flight_id', 'id_2013', 'id'] if c in df.columns]
    if cols_to_drop:
        print(f"            Dropping legacy ID columns: {cols_to_drop}")
        df.drop(columns=cols_to_drop, inplace=True)
        
    df.insert(0, 'flight_id', range(len(df)))
    
    print(f"            ✅ Generated {len(df)} unique sequential flight IDs (Done in {time.time() - step_start:.4f} seconds)\n")
    print(f"            Sample: {df['flight_id'].head(3).tolist()}")
    return df

def parse_time_to_datetime(df: pd.DataFrame, time_col: str, step: int) -> pd.Series:
    print(f"    Step {step}: parse_time_to_datetime for '{time_col}' ---")
    step_start = time.time()
    mask = df[time_col].notna()
    print(f"            Valid (non-null) rows to parse: {mask.sum()} out of {len(df)}")
    
    time_vals = df.loc[mask, time_col].astype(int)
    
    hours = time_vals // 100
    minutes = time_vals % 100
    
    midnight_count = (hours == 24).sum()
    if midnight_count > 0:
        print(f"            Adjusted {midnight_count} instances of 24:00 to 00:00.")
    hours = hours.replace(24, 0)
    
    dt_df = pd.DataFrame({
        'year': df.loc[mask, 'year'],
        'month': df.loc[mask, 'month'],
        'day': df.loc[mask, 'day'],
        'hour': hours,
        'minute': minutes
    })
    
    parsed_series = pd.to_datetime(dt_df)
    sample_str = parsed_series.head(2).to_string().replace('\n', '\n            ')
    print(f"            ✅ Successfully parsed {len(parsed_series)} dates  (Done in {time.time() - step_start:.4f} seconds)\n")
    print(f"            Sample:\n            {sample_str}")

    return parsed_series

def process_datetimes(df: pd.DataFrame) -> pd.DataFrame:
    time_cols = ['dep_time', 'sched_dep_time', 'arr_time', 'sched_arr_time']
    step = 1
    for col in time_cols:
        if col in df.columns:
            df[col] = parse_time_to_datetime(df, col, step)
            step = step + 1
        else:
            print(f"            ⚠️ WARNING: Column '{col}' not found in dataframe!")
            
    if 'arr_time' in df.columns and 'dep_time' in df.columns:
        midnight_mask = df['arr_time'] < df['dep_time']
        cross_midnight_count = midnight_mask.sum()
        print(f"            ✅ Found {cross_midnight_count} cross-midnight actual flights. Adjusting arr_time +1 day.")
        df.loc[midnight_mask, 'arr_time'] += pd.Timedelta(days=1)
        
    if 'sched_arr_time' in df.columns and 'sched_dep_time' in df.columns:
        sched_midnight_mask = df['sched_arr_time'] < df['sched_dep_time']
        cross_midnight_sched = sched_midnight_mask.sum()
        print(f"            ✅ Found {cross_midnight_sched} cross-midnight scheduled flights. Adjusting sched_arr_time +1 day.\n")
        df.loc[sched_midnight_mask, 'sched_arr_time'] += pd.Timedelta(days=1)
        
    return df

def standardize_data_types(df: pd.DataFrame) -> pd.DataFrame:
    print("    Step 5: standardize_data_types")
    step_start = time.time()
    numeric_cols = [
        'dep_delay', 'arr_delay', 'air_time', 'distance', 
        'taxi_out', 'taxi_in', 'sched_time_elapsed', 'actual_time_elapsed',
        'air_system_delay', 'security_delay', 'airline_delay', 
        'late_aircraft_delay', 'weather_delay', 'cancelled', 'diverted'
    ]
    
    converted = 0
    for col in numeric_cols:
        if col in df.columns:
            try:
                df[col] = df[col].astype('Int64')
                converted += 1
            except Exception as e:
                print(f"            ❌ ERROR converting {col}: {e}")
        else:
            print(f"            ⚠️ WARNING: Skip casting '{col}': not in dataframe.")
            
    print(f"            ✅ Successfully converted {converted} columns to Int64 in {time.time() - step_start:.4f} seconds\n")
    return df

def replace_with_foreign_keys(df: pd.DataFrame, airports_path: str, airlines_path: str) -> pd.DataFrame:
    print("    Step 6: replace_with_foreign_keys ")
    step_start = time.time()
    try:
        print(f"            Loading {airports_path}...")
        airports_df = pd.read_csv(airports_path, sep=None, engine='python')
        print(f"            Loading {airlines_path}...")
        airlines_df = pd.read_csv(airlines_path, sep=None, engine='python')
        
        airports_df = standardize_column_names(airports_df)
        airlines_df = standardize_column_names(airlines_df)
        
        print(f"            ✅ Loaded airports: {airports_df.shape}, airlines: {airlines_df.shape}")
        
        airline_id_col = next((c for c in airlines_df.columns if 'airline_id' in c or c == 'id'), 'airline_id')
        airline_code_col = next((c for c in airlines_df.columns if 'iata' in c or 'code' in c), 'iata')
        
        airport_id_col = next((c for c in airports_df.columns if 'airport_id' in c or c == 'id'), 'airport_id')
        airport_code_col = next((c for c in airports_df.columns if c == 'iata' or 'iata' in c), 'iata')

        if airline_code_col in airlines_df.columns:
            airlines_df[airline_code_col] = airlines_df[airline_code_col].astype(str).str.strip().str.upper()
            airlines_df = airlines_df.drop_duplicates(subset=[airline_code_col])
            
        if airport_code_col in airports_df.columns:
            airports_df[airport_code_col] = airports_df[airport_code_col].astype(str).str.strip().str.upper()
            airports_df = airports_df.drop_duplicates(subset=[airport_code_col])

        has_error = False
        
        if airline_id_col in airlines_df.columns and airline_code_col in airlines_df.columns:
            df = df.merge(airlines_df[[airline_id_col, airline_code_col]], 
                          left_on='airline_code', 
                          right_on=airline_code_col, 
                          how='left')
            df = df.rename(columns={airline_id_col: 'airline_id'})
            if airline_code_col != 'airline_code' and airline_code_col in df.columns:
                df = df.drop(columns=[airline_code_col])
        else:
            print(f"            ❌ Error: Could not find {airline_code_col}")
            has_error = True
                
        if airport_id_col in airports_df.columns and airport_code_col in airports_df.columns:
            df = df.merge(airports_df[[airport_id_col, airport_code_col]], 
                          left_on='origin_airport', 
                          right_on=airport_code_col, 
                          how='left')
            df = df.rename(columns={airport_id_col: 'origin_airport_id'})
            if airport_code_col in df.columns:
                df = df.drop(columns=[airport_code_col])
        else:
            print(f"            ❌ Error: Could not find {airport_code_col}")
            has_error = True
                
        if airport_id_col in airports_df.columns and airport_code_col in airports_df.columns:
            df = df.merge(airports_df[[airport_id_col, airport_code_col]], 
                          left_on='destination_airport', 
                          right_on=airport_code_col, 
                          how='left')
            df = df.rename(columns={airport_id_col: 'dest_airport_id'})
            if airport_code_col in df.columns:
                df = df.drop(columns=[airport_code_col])
        else:
            print(f"            ❌ Error: Could not find {airport_code_col}")
            has_error = True
        
        cols_to_drop = ['airline_code', 'airline_name', 'origin_airport', 'destination_airport']
        existing_cols = [c for c in cols_to_drop if c in df.columns]
        df = df.drop(columns=existing_cols)

        if has_error:
            print("            ❌ ERROR in replace_with_foreign_keys")
        else:
            print(f"            ✅ Successfully joined IDs.\n            ⚠️  Dropped string columns: {existing_cols} because no more useful")
        
        null_origins = df['origin_airport_id'].isnull().sum() if 'origin_airport_id' in df.columns else 0
        if null_origins > 0:
            print(f"            ⚠️ WARNING: {null_origins} flights have an unknown origin_airport_id!")

    except Exception as e:
        print(f"            ❌ ERROR in replace_with_foreign_keys: {e}")
        
    print(f"            ✅ Done in {time.time() - step_start:.4f} seconds\n")
    return df

def drop_redundant_columns(df: pd.DataFrame) -> pd.DataFrame:
    print("    Step 7: drop_redundant_columns ")
    step_start = time.time()
    cols_to_drop = [
        'sched_hour', 'sched_minute', 'time_hour_str', 'day_of_week',
        'year', 'month', 'day'
    ]
    existing_cols = [col for col in cols_to_drop if col in df.columns]
    print(f"            ⚠️  Attempting to drop: {cols_to_drop}")
    print(f"            ✅ Actually dropping:  {existing_cols}")
    df = df.drop(columns=existing_cols)
    print(f"            ✅ Done in {time.time() - step_start:.4f} seconds\n")
    return df

def main_etl_pipeline(input_filepath: str, output_filepath: str, airports_path: str, airlines_path: str) -> pd.DataFrame:
    func_start = time.time()
    print("    Step 0: loading " + input_filepath)
    step_start = time.time()
    try:
        df = pd.read_csv(input_filepath, sep=None, engine='python')
        df = standardize_column_names(df)
        print(f"            ✅ Loaded dataframe with shape {df.shape}  (Done in {time.time() - step_start:.4f} seconds)")
        
    except FileNotFoundError:
        print(f"            ❌ FATAL ERROR: Could not find file {input_filepath}")
        return None
    
    df = process_datetimes(df)
    df = standardize_data_types(df)
    df = replace_with_foreign_keys(df, airports_path, airlines_path)
    df = drop_redundant_columns(df)
    
    df = generate_flight_id(df)
    
    print("    Step 9: Saving final CSV file ")
    step_start = time.time()
    df.to_csv(output_filepath, sep=',', index=False)
    print(f"            ✅ Done in {time.time() - step_start:.4f} seconds\n")

    print("\n" + "="*103)
    print(f"SUCCESS: Entire ETL pipeline and cleaning workflow completed successfully, executed in {time.time() - func_start:.4f} seconds")
    print(f"Final dataframe shape: {df.shape}")
    print(f"Saved to {output_filepath}.")
    print("="*103 + "\n")

    return df

# ==========================================================
# FUNCTION 5: LAST ADJUSTMENTS AND DATA TYPES NORMALIZATION
# ==========================================================
def clean_csv_columns_inplace(directory_path: str) -> None:

    print("    Step 1: Verify and standardize final CSV formats and lowercased headers...")
    step_start = time.time()
    in_path = Path(directory_path)
    csv_files = list(in_path.glob("*.csv"))
    print(f"            Found {len(csv_files)} CSV file(s) to process.")
    
    for file_path in csv_files:
        df = pd.read_csv(file_path, sep=None, engine='python')
        df = standardize_column_names(df)
        df.to_csv(file_path, sep=',', index=False)
        print(f"            ✅ Verified & standardized: {file_path.name}")
        
    print(f"            ✅ Done in {time.time() - step_start:.4f} seconds\n")

def drop_denormalized_columns():
    print("    Step 2: Dropping denormalized string columns (country, route IATA/ICAO codes)...")
    step_start = time.time()

    cols_to_drop = ['airports.country', 'airline.country', 'airline_iata/icao', 'source_iata/icao', 'destination_iata_icao', 'plane_iata/icao']
    print(f"            ⚠️  Attempting to drop: {cols_to_drop}")
    
    
    if os.path.exists(MERGED_AIRPORTS_PATH):
        df = pd.read_csv(MERGED_AIRPORTS_PATH, low_memory=False)
        df = df.drop(columns=['state', 'country'], errors='ignore')
        df.to_csv(MERGED_AIRPORTS_PATH, sep=',', index=False)
        
    if os.path.exists(AIRLINES_PATH):
        df = pd.read_csv(AIRLINES_PATH, low_memory=False)
        df = df.drop(columns=['country', 'state'], errors='ignore')
        df.to_csv(AIRLINES_PATH, sep=',', index=False)
        
    if os.path.exists(ROUTES_PATH):
        df = pd.read_csv(ROUTES_PATH, low_memory=False)
        df = df.drop(columns=[
            'airline', 'source_airport', 'destination_airport', 'equipment',
            'airlines_iata_icao', 'source_airport_iata_icao', 'destination_airport_iata_icao', 'plane_iata_icao'
        ], errors='ignore')
        df.to_csv(ROUTES_PATH, sep=',', index=False)
    
    print(f"            ✅ Actually dropping:  {cols_to_drop}")
        
    print(f"            ✅ Done in {time.time() - step_start:.4f} seconds\n")

def assign_route_ids_to_flights():
    print("    Step 3: Cross-referencing flights against routes.csv and assigning route_id...")
    step_start = time.time()

    if not os.path.exists(FLIGHTS_CLEANED_PATH):
        print(f"            ❌ Error: {FLIGHTS_CLEANED_PATH} not found! Skipping route_id assignment.")
        return
    if not os.path.exists(ROUTES_PATH):
        print(f"            ❌ Error: {ROUTES_PATH} not found! Skipping route_id assignment.")
        return

    print(f"            Loading {ROUTES_PATH}...")
    df_routes = pd.read_csv(ROUTES_PATH, low_memory=False)
    df_routes = standardize_column_names(df_routes)

    print(f"            Loading {FLIGHTS_CLEANED_PATH}...")
    df_flights = pd.read_csv(FLIGHTS_CLEANED_PATH, low_memory=False)
    df_flights = standardize_column_names(df_flights)

    required_flight_cols = ['airline_id', 'origin_airport_id', 'dest_airport_id']
    required_route_cols = ['route_id', 'airline_id', 'source_airport_id', 'destination_airport_id']
    missing_flight = [c for c in required_flight_cols if c not in df_flights.columns]
    missing_route = [c for c in required_route_cols if c not in df_routes.columns]
    if missing_flight or missing_route:
        print(f"            ❌ Error: missing required columns. Flights missing: {missing_flight}, Routes missing: {missing_route}")
        print(f"            ✅ Done in {time.time() - step_start:.4f} seconds\n")
        return

    for col in required_flight_cols:
        df_flights[col] = pd.to_numeric(df_flights[col], errors='coerce')
    for col in ['airline_id', 'source_airport_id', 'destination_airport_id']:
        df_routes[col] = pd.to_numeric(df_routes[col], errors='coerce')
    df_routes['route_id'] = pd.to_numeric(df_routes['route_id'], errors='coerce')

    if 'route_id' in df_flights.columns:
        df_flights = df_flights.drop(columns=['route_id'])

    route_lookup_df = (
        df_routes.dropna(subset=['airline_id', 'source_airport_id', 'destination_airport_id'])
        .groupby(['airline_id', 'source_airport_id', 'destination_airport_id'], as_index=False)['route_id']
        .min()
        .rename(columns={
            'source_airport_id': 'origin_airport_id',
            'destination_airport_id': 'dest_airport_id'
        })
    )
    print(f"            Matching {len(df_flights)} flights against {len(route_lookup_df)} unique existing routes...")

    df_flights = df_flights.merge(
        route_lookup_df,
        on=['airline_id', 'origin_airport_id', 'dest_airport_id'],
        how='left'
    )
    matched_count = int(df_flights['route_id'].notna().sum())

    has_full_key = df_flights[required_flight_cols].notna().all(axis=1)
    unmatched_mask = df_flights['route_id'].isna() & has_full_key
    unmatched_combos = (
        df_flights.loc[unmatched_mask, required_flight_cols]
        .drop_duplicates()
        .reset_index(drop=True)
    )

    next_route_id = int(df_routes['route_id'].max()) + 1 if df_routes['route_id'].notna().any() else 1
    unmatched_combos['new_route_id'] = range(next_route_id, next_route_id + len(unmatched_combos))

    df_flights = df_flights.merge(
        unmatched_combos,
        on=required_flight_cols,
        how='left'
    )
    df_flights['route_id'] = df_flights['route_id'].fillna(df_flights['new_route_id'])
    df_flights = df_flights.drop(columns=['new_route_id'])
    df_flights['route_id'] = df_flights['route_id'].astype('Int64')

    skipped_count = int(df_flights['route_id'].isna().sum())
    print(f"            ✅ Matched {matched_count} flights to already-existing routes.")
    print(f"            ✅ Created {len(unmatched_combos)} brand-new routes not previously present in routes.csv.")
    if skipped_count:
        print(f"            ⚠️ {skipped_count} flights had incomplete airline/airport keys and were left without a route_id.")

    if len(unmatched_combos) > 0:
        df_new_routes = unmatched_combos.rename(columns={
            'origin_airport_id': 'source_airport_id',
            'dest_airport_id': 'destination_airport_id',
            'new_route_id': 'route_id'
        })
        for col in df_routes.columns:
            if col not in df_new_routes.columns:
                df_new_routes[col] = np.nan
        df_new_routes = df_new_routes[df_routes.columns]
        df_routes = pd.concat([df_routes, df_new_routes], ignore_index=True)

    if 'flight_id' in df_flights.columns:
        cols = [c for c in df_flights.columns if c != 'route_id']
        idx = cols.index('flight_id') + 1
        cols.insert(idx, 'route_id')
        df_flights = df_flights[cols]

    print(f"            Saving updated {ROUTES_PATH}...")
    df_routes.to_csv(ROUTES_PATH, sep=',', index=False)

    print(f"            Saving updated {FLIGHTS_CLEANED_PATH}...")
    df_flights.to_csv(FLIGHTS_CLEANED_PATH, sep=',', index=False)

    print(f"            ✅ Done in {time.time() - step_start:.4f} seconds\n")

def normalize_csv_data_types():
    step_start = time.time()
    print("    Step 4: Normalize data types")

    in_path = Path(DATA_DIR)
    csv_files = list(in_path.glob("*.csv"))

    for file_path in csv_files:
        print(f"            Processing {file_path.name}...")
        df = pd.read_csv(file_path, low_memory=False)
        
        df.columns = df.columns.str.strip()

        for col in df.columns:
            col_lower = col.lower()

            if pd.api.types.is_object_dtype(df[col]):
                df[col] = df[col].astype(str).str.strip().replace(
                    {'\\N': None, 'nan': None, 'NaN': None, 'None': None, '<NA>': None, '': None}
                )

            if col_lower in ['latitude', 'longitude', 'lat', 'lon', 'lng']:
                df[col] = pd.to_numeric(df[col], errors='coerce').astype('float64')

            elif (col_lower.endswith('_id') or 
                  'delay' in col_lower or 
                  col_lower in ['year', 'month', 'day', 'flight', 'altitude', 'tz', 'seats', 'air_time', 'distance', 'cancelled', 'diverted']):
                
                df[col] = pd.to_numeric(df[col], errors='coerce').astype('Int64')

        df.to_csv(file_path, index=False, na_rep='')
        print(f"            ✅ Normalized data types for {file_path.name}")

    print(f"            ✅ Done in {time.time() - step_start:.4f} seconds.")

# ==========================================================
# FUNCTION 6: RUN CORRECTNESS TESTS
# ==========================================================
def run_correctness_tests():
    func_start = time.time()
    step_start = time.time()
    try:
        result = subprocess.run(['python3', 'correctness_tests.py'], check=True, text=True, capture_output=True)
        print(result.stdout)
    except subprocess.CalledProcessError as e:
        print("            ❌ Error running correctness_tests.py:\n")
        if e.stdout:
            print(e.stdout)
        if e.stderr:
            print(e.stderr)
        raise
    except FileNotFoundError:
        print("            ❌ Error: correctness_tests.py not found in the current directory.")
        raise

    print("\n" + "="*80)
    print(f"SUCCESS: Correctness tests completed successfully, executed in {time.time() - func_start:.4f} seconds")
    print("="*80 + "\n")

# ==========================================================
# FUNCTION 7: FILE DELETION 
# ==========================================================
def delete_used_files():
    func_start = time.time()
    
    print("    Step 1: Deleting used files: airports.csv and airports-dafif.csv")
    step_start = time.time()
    for file_path in [AIRPORTS_PATH, DAFIF_PATH]:
        if os.path.exists(file_path):
            os.remove(file_path)
            print(f"            ✅ Deleted source file: {file_path}")
        else: 
            print(f"            ❌ File not found: {file_path}")
    print(f"            ✅ Done in {time.time() - step_start:.4f} seconds\n")

    print("    Step 2: Deleting used files: flights_2013.csv and flights_2015.csv")
    step_start = time.time()
    for file_path in [FLIGHTS_2013, FLIGHTS_2015]:
        if os.path.exists(file_path):
            os.remove(file_path)
            print(f"            ✅ Deleted source file: {file_path}")
        else: 
            print(f"            ❌ File not found: {file_path}")
    print(f"            ✅ Done in {time.time() - step_start:.4f} seconds\n")

    print("    Step 3: Deleting used file: merged_flights.csv")
    step_start = time.time()
    for file_path in [FLIGHTS_PATH]:
        if os.path.exists(file_path):
            os.remove(file_path)
            print(f"            ✅ Deleted source file: {file_path}")
        else: 
            print(f"            ❌ File not found: {file_path}")
    print(f"            ✅ Done in {time.time() - step_start:.4f} seconds\n")

    print("\n" + "="*86)
    print(f"SUCCESS: deleting garbage files completed successfully, executed in {time.time() - func_start:.4f} seconds")
    print("="*86 + "\n")

# ==========================================================
# MAIN EXECUTION FLOW
# ==========================================================
if __name__ == '__main__':
    total_start_time = time.time()

    # 1. Clean and Merge Airports
    clean_and_merge_airports()

    # 2. Merge 2013 and 2015 Flights into unified master file
    merge_flights()

    # 3. Perform Relational Adjustments & Country Mappings
    print("FUNCTION_3: RELATIONAL ADJUSTMENTS\n")
    func3_start = time.time()
    step_0_standardize_separators(DATA_DIR)
    df_countries = step_1_process_countries(COUNTRIES_PATH)
    df_planes = step_2_process_planes(PLANES_PATH)
    step_3_process_routes(ROUTES_PATH, df_planes)
    step_4_map_country_ids(df_countries, MERGED_AIRPORTS_PATH, AIRLINES_PATH)

    print("\n" + "="*90)
    print(f"SUCCESS: All relational adjustments completed successfully, executed in {time.time() - func3_start:.4f} seconds")
    print("="*90 + "\n")

    # 4. Run the Flight Cleaning & Foreign Key Mapping Pipeline
    print("FUNCTION_4: FLIGHT ETL & CLEANING PIPELINE\n")
    processed_flights_df = main_etl_pipeline(
        input_filepath=FLIGHTS_PATH,
        output_filepath=FLIGHTS_CLEANED_PATH,
        airports_path=MERGED_AIRPORTS_PATH,
        airlines_path=AIRLINES_PATH
    )

    # 5. Make last modifications
    print("FUNCTION_5: DO LAST MODIFICATIONS AND NORMALIZE DATA TYPES\n")
    func5_start = time.time()

    clean_csv_columns_inplace(DATA_DIR) 

    drop_denormalized_columns()

    assign_route_ids_to_flights()

    normalize_csv_data_types()

    print("\n" + "="*100)
    print(f"SUCCESS: Last modifications and data types normalization completed, executed in {time.time() - func5_start:.4f} seconds")
    print("="*100 + "\n")

    # 6. Run Correctness Tests
    print("FUNCTION_6: RUN CORRECTNESS TESTS\n")
    run_correctness_tests()

    # 7. Delete no longer useful files
    print("FUNCTION_7: DELETE GARBAGE FILES \n")
    delete_used_files()

    print(f"TOTAL EXECUTION TIME {time.time() - total_start_time:.4f} seconds")