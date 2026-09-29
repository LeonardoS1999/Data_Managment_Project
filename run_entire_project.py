import os
import sys
import time
import json
import socket
import subprocess
from pathlib import Path

# ==========================================================
# INFERRED CONNECTION CONFIGURATION
# ==========================================================
SQL_USER = os.environ.get('DB_USER', 'admin')
SQL_PASSWORD = os.environ.get('DB_PASSWORD', 'supersecretpassword')
SQL_HOST = os.environ.get('DB_HOST', 'localhost')
SQL_PORT = int(os.environ.get('DB_PORT', '5432'))

NEO4J_URI = os.environ.get('NEO4J_URI', 'bolt://localhost:7687')
NEO4J_HOST = 'localhost'
NEO4J_PORT = 7687

DATA_DIR = Path('DATA_USED')

REQUIRED_PACKAGES = ['pandas', 'numpy', 'psycopg2-binary', 'psycopg[binary]', 'neo4j', 'sqlalchemy', 'psycopg']

INITIAL_8_FILES = [
    'airlines.csv',
    'airports.csv',
    'airports-dafif.csv',
    'countries.csv',
    'flights_2013.csv',
    'flights_2015.csv',
    'planes.csv',
    'routes.csv'
]

PROCESSED_6_FILES = [
    'airlines.csv',
    'countries.csv',
    'merged_airports.csv',
    'merged_flights_cleaned.csv',
    'planes.csv',
    'routes.csv'
]


# ==========================================================
# HELPER FUNCTIONS
# ==========================================================
def print_section(title):
    print("\n" + "=" * 80)
    print(f" {title}")
    print("=" * 80)


def run_venv_command(cmd_str, capture_output=False, check=True):
    """
    Activates the virtual environment using 'source' before executing the target command.
    """
    venv_dir = Path(".venv")
    if sys.platform == "win32":
        activate_script = venv_dir / "Scripts" / "activate.bat"
        full_cmd = f'"{activate_script}" && {cmd_str}'
        executable = None
    else:
        activate_script = venv_dir / "bin" / "activate"
        full_cmd = f'source "{activate_script}" && {cmd_str}'
        executable = "/bin/bash"

    result = subprocess.run(
        full_cmd,
        shell=True,
        executable=executable,
        text=True,
        capture_output=capture_output
    )

    if check and result.returncode != 0:
        print(f"❌ Command failed with return code {result.returncode}: {full_cmd}")
        sys.exit(result.returncode)

    return result


def check_port_open(host, port, timeout=3):
    """Checks if a TCP port is open and accepting connections."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False


def wait_for_port(host, port, service_name, timeout=90):
    """Waits until a service is listening on a target port."""
    print(f"⏳ Waiting for {service_name} at {host}:{port}...")
    start_time = time.time()
    while time.time() - start_time < timeout:
        if check_port_open(host, port):
            print(f"✅ {service_name} is up and accepting connections!")
            return True
        time.sleep(2)
    print(f"❌ Timeout waiting for {service_name} on {host}:{port}.")
    sys.exit(1)


# ==========================================================
# STEP 1: VIRTUAL ENVIRONMENT CHECK & SETUP
# ==========================================================
def setup_environment():
    print_section("STEP 1: CHECKING / CREATING VIRTUAL ENVIRONMENT")
    
    venv_dir = Path(".venv")

    if not venv_dir.exists():
        print("⚙️ Virtual environment '.venv' not found. Creating missing environment...")
        subprocess.run([sys.executable, "-m", "venv", str(venv_dir)], check=True)
        print("✅ Environment created successfully.")
        missing_packages = REQUIRED_PACKAGES
    else:
        print("✅ Virtual environment '.venv' already exists. Checking installed dependencies...")
        try:
            res = run_venv_command("pip list --format=json", capture_output=True, check=True)
            installed_data = json.loads(res.stdout)
            installed_names = {item['name'].lower().replace('-', '_') for item in installed_data}
            missing_packages = [
                pkg for pkg in REQUIRED_PACKAGES 
                if pkg.lower().replace('-', '_') not in installed_names
            ]
        except Exception:
            missing_packages = REQUIRED_PACKAGES

    if missing_packages:
        print(f"⚙️ Missing package(s) detected: {', '.join(missing_packages)}. Installing via activated venv...")
        run_venv_command("pip install --upgrade pip")
        run_venv_command(f"pip install {' '.join(missing_packages)}")
        print("✅ All missing packages installed successfully.")
    else:
        print("✅ All required packages are already installed.")


# ==========================================================
# STEP 2: VERIFY DATA_USED FILES & PREPARATOR EXECUTION
# ==========================================================
def verify_and_prepare_data():
    print_section("STEP 2: CHECKING DATA_USED FILES")

    if not DATA_DIR.exists():
        print(f"❌ Directory '{DATA_DIR}' does not exist.")
        sys.exit(1)

    has_8_files = all((DATA_DIR / f).exists() for f in INITIAL_8_FILES)
    has_6_files = all((DATA_DIR / f).exists() for f in PROCESSED_6_FILES)

    if has_8_files:
        print("✅ Found all 8 raw input files in DATA_USED. Running data_preparator_script.py...")
        run_venv_command("python data_preparator_script.py")
    elif has_6_files:
        print("✅ Found all 6 processed files in DATA_USED. Skipping preparation step and proceeding.")
    else:
        print("❌ Dataset check failed!")
        print(f"Directory '{DATA_DIR}' contains neither the full 8 raw files nor the 6 processed files.")
        print("Terminating execution.")
        sys.exit(1)


# ==========================================================
# STEP 3: START / VERIFY NEO4J
# ==========================================================
def ensure_neo4j():
    print_section("STEP 3: CHECKING NEO4J SERVICE")

    if check_port_open(NEO4J_HOST, NEO4J_PORT):
        print(f"✅ Neo4j is already running on port {NEO4J_PORT}.")
        return

    print("⚙️ Neo4j not detected on port 7687. Attempting to start Neo4j service...")

    commands = [
        ["sudo", "systemctl", "start", "neo4j"],
        ["sudo", "service", "neo4j", "start"],
        ["docker", "start", "neo4j"]
    ]

    started = False
    for cmd in commands:
        try:
            print(f"⚙️ Running command: {' '.join(cmd)}")
            res = subprocess.run(cmd, check=False)
            if res.returncode == 0:
                started = True
                break
        except FileNotFoundError:
            continue

    if not started:
        print("⚠️ Failed to start via system services. Trying 'sudo neo4j start' as fallback...")
        subprocess.run(["sudo", "neo4j", "start"], check=False)

    wait_for_port(NEO4J_HOST, NEO4J_PORT, "Neo4j Database")


# ==========================================================
# STEP 4: DOCKER SERVICES SETUP & WAITING
# ==========================================================
def start_docker_services():
    print_section("STEP 4: RUNNING DOCKER & WAITING FOR HEALTH CHECK")

    print("⚙️ Executing Docker Compose down...")
    subprocess.run(["docker", "compose", "down", "--remove-orphans", "-v"], check=False)

    # Automatically extract container_name entries from docker-compose file and purge them
    for yaml_path in [Path("docker-compose.yml"), Path("docker-compose.yaml")]:
        if yaml_path.exists():
            try:
                with open(yaml_path, "r", encoding="utf-8") as f:
                    for line in f:
                        if "container_name:" in line:
                            c_name = line.split("container_name:")[1].strip().strip("'\"")
                            if c_name:
                                print(f"🧹 Cleaning up stale container if present: '{c_name}'...")
                                subprocess.run(["docker", "rm", "-f", c_name], check=False)
            except Exception as e:
                print(f"⚠️ Warning reading {yaml_path}: {e}")

    print("⚙️ Building and starting container services via Docker Compose...")
    docker_cmd = ["docker", "compose", "up", "-d", "--build"]
    subprocess.run(docker_cmd, check=True)

    wait_for_port(SQL_HOST, SQL_PORT, "PostgreSQL Database")


# ==========================================================
# STEP 9: CLEANUP / SHUTDOWN SERVICES
# ==========================================================
def stop_services():
    print_section("STOPPING DOCKER & NEO4J SERVICES")

    print("⚙️ Stopping Docker Compose services...")
    subprocess.run(["docker", "compose", "down"], check=False)

    print("⚙️ Stopping Neo4j service...")
    stop_commands = [
        ["sudo", "systemctl", "stop", "neo4j"],
        ["sudo", "service", "neo4j", "stop"],
        ["docker", "stop", "neo4j"]
    ]

    for cmd in stop_commands:
        try:
            res = subprocess.run(cmd, check=False)
            if res.returncode == 0:
                break
        except FileNotFoundError:
            continue

    print("✅ All services stopped successfully.")


# ==========================================================
# PIPELINE ORCHESTRATION
# ==========================================================
def main():
    # Step 1: Environment Check/Creation & Requirements Inspection
    setup_environment()

    # Step 2: Data Pre-processing check
    verify_and_prepare_data()

    # Step 3: Start/Verify Neo4j
    ensure_neo4j()

    # Step 4: Start Docker Services (PostgreSQL) and wait
    start_docker_services()

    # Step 5: Load SQL Database
    print_section("STEP 5: RUNNING SQL DATABASE LOADER")
    run_venv_command("python sql_db_loader.py")

    # Step 6: Load Neo4j Schema A
    print_section("STEP 6: RUNNING NEO4J SCHEMA A LOADER")
    run_venv_command("python neo4j_db_schemaA_loader.py")

    # Step 7: Load Neo4j Schema B
    print_section("STEP 7: RUNNING NEO4J SCHEMA B LOADER")
    run_venv_command("python neo4j_db_schemaB_loader.py")

    # Step 8: Run Benchmark Suite in Sequence
    print_section("STEP 8: EXECUTING BENCHMARK SCRIPTS")
    
    print("\n▶ [1/3] Running Standard Benchmarks (benchmark_runner.py)...")
    run_venv_command("python benchmark_runner.py")

    print("\n▶ [2/3] Running Heavy Benchmarks (benchmark_runner_heavy.py)...")
    run_venv_command("python benchmark_runner_heavy.py")

    print("\n▶ [3/3] Running Depth Scaling Benchmarks (benchmark_depth_scaling.py)...")
    run_venv_command("python benchmark_depth_scaling.py")

    print_section("🎉 ALL PIPELINE STEPS COMPLETED SUCCESSFULLY!")

    # Final prompt asking user if they want to stop services
    choice = input("\n❓ Do you want to stop Neo4j and Docker services before exiting? (y/N): ").strip().lower()
    if choice in ['y', 'yes']:
        stop_services()
    else:
        print("⏩ Leaving Neo4j and Docker services running.")

    print("\n👋 Process finished. Exiting script.")


if __name__ == "__main__":
    main()