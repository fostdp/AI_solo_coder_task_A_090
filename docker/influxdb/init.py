import os
import sys
import time
import json
from influxdb_client import InfluxDBClient, Point, BucketRetentionRules
from influxdb_client.client.write_api import SYNCHRONOUS

INFLUXDB_URL = os.getenv("INFLUXDB_URL", "http://influxdb:8086")
INFLUXDB_TOKEN = os.getenv("INFLUXDB_TOKEN", "my-super-secret-auth-token")
INFLUXDB_ORG = os.getenv("INFLUXDB_ORG", "agri-history")
INFLUXDB_USER = os.getenv("INFLUXDB_USERNAME", "admin")
INFLUXDB_PASS = os.getenv("INFLUXDB_PASSWORD", "adminpassword123")
CONFIG_PATH = os.getenv("INFLUXDB_CONFIG_PATH", "/app/config/influxdb/config.json")


def wait_for_influxdb(client, max_retries=30, delay=3):
    for i in range(max_retries):
        try:
            health = client.health()
            if health.status == "pass":
                print(f"InfluxDB 就绪 ({i * delay}s)")
                return True
        except Exception:
            pass
        print(f"等待 InfluxDB 启动... ({i + 1}/{max_retries})")
        time.sleep(delay)
    return False


def init_influxdb():
    client = InfluxDBClient(url=INFLUXDB_URL, token=INFLUXDB_TOKEN, org=INFLUXDB_ORG)

    if not wait_for_influxdb(client):
        print("InfluxDB 启动超时，退出")
        sys.exit(1)

    try:
        buckets_api = client.buckets_api()
        orgs_api = client.organizations_api()
        tasks_api = client.tasks_api()

        orgs = orgs_api.find_organizations()
        org_id = None
        for org in orgs:
            if org.name == INFLUXDB_ORG:
                org_id = org.id
                break

        if not org_id:
            org = orgs_api.create_organization(name=INFLUXDB_ORG)
            org_id = org.id
            print(f"创建组织: {INFLUXDB_ORG}")

        config = {}
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                config = json.load(f)

        for bucket_cfg in config.get("buckets", []):
            name = bucket_cfg["name"]
            existing = buckets_api.find_buckets(name=name).buckets
            if existing:
                print(f"Bucket '{name}' 已存在，跳过")
                continue

            retention_days = bucket_cfg.get("retention_days", 30)
            shard_hours = bucket_cfg.get("shard_group_duration_hours", 24)

            rules = BucketRetentionRules(
                type="expire",
                every_seconds=retention_days * 86400,
                shard_group_duration_seconds=shard_hours * 3600,
            )
            buckets_api.create_bucket(
                bucket_name=name,
                org_id=org_id,
                retention_rules=rules,
            )
            print(f"创建 Bucket: {name} (保留 {retention_days} 天)")

        for task_cfg in config.get("tasks", []):
            task_name = task_cfg["name"]
            existing_tasks = tasks_api.find_tasks(name=task_name)
            if existing_tasks:
                print(f"Task '{task_name}' 已存在，跳过")
                continue

            flux = task_cfg["flux"]
            every = task_cfg.get("every", "1h")
            offset = task_cfg.get("offset", "0s")

            task_flux = f'option task = {{name: "{task_name}", every: {every}, offset: {offset}}}\n\n{flux}'

            tasks_api.create_task(
                name=task_name,
                org=INFLUXDB_ORG,
                flux=task_flux,
                status="active",
            )
            print(f"创建降采样任务: {task_name} (间隔 {every})")

        write_test_data(client)

    except Exception as e:
        print(f"初始化失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        client.close()

    print("InfluxDB 初始化完成")


def write_test_data(client):
    write_api = client.write_api(write_options=SYNCHRONOUS)
    from datetime import datetime, timezone
    point = (
        Point("waterwheel_sensor")
        .tag("wheel_id", "test_wheel_001")
        .tag("location", "han_dynasty_museum")
        .field("rotational_speed", 10.0)
        .field("torque", 50.0)
        .field("water_lift", 100.0)
        .field("water_level_diff", 1.5)
        .field("drive_torque", 60.0)
        .field("efficiency", 0.75)
        .time(datetime.now(timezone.utc))
    )
    write_api.write(bucket="waterwheel_data", org=INFLUXDB_ORG, record=point)
    write_api.close()
    print("测试数据写入成功")


if __name__ == "__main__":
    init_influxdb()
