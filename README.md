# README

## Prerequisites
Ensure you have the following installed before starting:
* **Neo4j**
* **Docker**

To execute the entire project, you can choose between two methods.

---

## First Way
Open a terminal and type the following command to execute everything at once:

```bash
python3 run_entire_project.py
```

---

## Second Way: Step-by-Step

### 1. Create a New Environment
If you need to create a new virtual environment, run the following commands:

```bash
sudo apt update
sudo apt install -y python3.12-venv
rm -rf myenv
python3 -m venv myenv
source myenv/bin/activate
```

Install all requested libraries:
```bash
pip install pandas
pip install neo4j
pip install sqlalchemy
pip install psycopg2-binary
```
*(If your environment is already created, skip the creation steps and simply run `source myenv/bin/activate` in the project folder.)*

### 2. Start Docker
On another terminal, start your containers:
```bash
docker compose up --build
```

### 3. Run Data Preparator
Back on the first terminal (with the virtual environment activated), run:
```bash
python3 data_preparator_script.py
```

### 4. Load SQL Database
Run the SQL database loader script:
```bash
python3 sql_db_loader.py
```

### 5. Interact with the Database
If you want to interact with the database, you can use the web interface:
* Open a browser and go to `http://localhost:5050/`.
* Insert `admin@admin.com` as the username and `adminpassword` as the password.
* Once in, click on the **query tool** on the upper left side and insert the following connection details:
  * **Server:** whathever (flightdb)
  * **Host name/address:** postgres_db
  * **Port:** 5432
  * **Database:** flightdb
  * **Username:** admin
  * **Password:** supersecretpassword

### 6. Start Neo4j
Start the Neo4j service:
```bash
sudo systemctl start neo4j
```

### 7. Load Neo4j Schemas
Run the schema loader scripts:
```bash
python3 neo4j_db_schemaA_loader.py
python3 neo4j_db_schemaB_loader.py
```

### 8. Run Benchmarks
Execute the three benchmark scripts:
```bash
python3 benchmarch_runner.py
python3 benchmark_runner_heavy.py
python3 benchmark_depth_scaling.py
```

### 9. Stop Services
When you are finished, stop Neo4j and Docker by running the following commands:
```bash
sudo systemctl stop neo4j
docker compose down
```