"""Quick test to diagnose Databricks SQL connection issues."""
import os
from dotenv import load_dotenv

load_dotenv()

print("=== Databricks Connection Test ===\n")

# Check credentials
host = os.getenv("DATABRICKS_HOST")
token = os.getenv("DATABRICKS_TOKEN")
http_path = os.getenv("DATABRICKS_HTTP_PATH")

print(f"Host: {host}")
print(f"Token: {token[:10]}...{token[-4:] if token else 'NOT SET'}")
print(f"HTTP Path: {http_path}")
print()

if not all([host, token, http_path]):
    print("ERROR: Missing credentials in .env")
    exit(1)

# Try to import
try:
    from databricks import sql as databricks_sql
    print("✓ databricks-sql-connector installed")
except ImportError:
    print("✗ databricks-sql-connector NOT installed")
    print("  Run: pip install databricks-sql-connector")
    exit(1)

# Try to connect with timeout
print("\nAttempting connection (30 second timeout)...")
print("If the warehouse is stopped, it may take 1-2 minutes to start.\n")

import signal

def timeout_handler(signum, frame):
    raise TimeoutError("Connection timed out after 30 seconds")

signal.signal(signal.SIGALRM, timeout_handler)
signal.alarm(30)

try:
    conn = databricks_sql.connect(
        server_hostname=host.replace("https://", ""),
        http_path=http_path,
        access_token=token,
    )
    signal.alarm(0)  # Cancel timeout
    print("✓ Connected successfully!")
    
    # Try a simple query
    cursor = conn.cursor()
    cursor.execute("SELECT 1")
    result = cursor.fetchone()
    print(f"✓ Query test passed: {result}")
    
    # Check if few_shot_examples table exists
    try:
        cursor.execute("SELECT COUNT(*) FROM few_shot_examples")
        count = cursor.fetchone()[0]
        print(f"✓ few_shot_examples table exists with {count} rows")
    except Exception as e:
        print(f"✗ few_shot_examples table not found: {e}")
    
    cursor.close()
    conn.close()
    print("\n=== Connection test PASSED ===")
    
except TimeoutError as e:
    print(f"✗ {e}")
    print("\nThe warehouse might be:")
    print("  - Stopped (go to Databricks UI to start it)")
    print("  - Behind a firewall")
    print("  - The HTTP path might be wrong")
    
except Exception as e:
    signal.alarm(0)
    print(f"✗ Connection failed: {e}")
    print("\nPossible issues:")
    print("  - Token expired (generate a new one in Databricks)")
    print("  - Wrong HTTP path")
    print("  - Warehouse deleted")
