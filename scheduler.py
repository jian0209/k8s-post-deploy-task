from kubernetes import client, config
from kubernetes.client import V1EnvVar, V1Volume, V1VolumeMount, V1ConfigMapVolumeSource, V1SecretKeySelector, V1EnvVarSource
import schedule
from time import time, sleep
import os
import json


AGE_THRESHOLD_SECONDS = 60 * 5  # 5 minutes
OVER_AGE_THRESHOLD_SECONDS = 60 * 30  # 30 minutes
LOCK_FILE_DIR = "kopf-locks"


def create_jobs(app_name: str, app_annotations: dict):
    try:
        print(f"Annotations:::: >>>> {app_annotations}")
        print(f"Creating job for {app_name}...")
        job_namespace = os.getenv("JOB_NAMESPACE", "default")
        print(f"Using namespace: {job_namespace}")
        job_script_cm = os.getenv(
            "JOB_SCRIPT_CONFIG_MAP", "test-python-configmap")
        print(f"Using ConfigMap for job script: {job_script_cm}")
        job_script = os.getenv("JOB_SCRIPT_NAME", "telegram_notify.py")
        print(f"Using job script: {job_script}")
        job_script_mount_path = os.getenv("JOB_SCRIPT_MOUNT_PATH", "/mnt/exec")
        print(f"Mounting job script at: {job_script_mount_path}")

        container_image_name = os.getenv(
            "JOB_IMAGE", "python:3.10.17-alpine3.21")
        print(f"Using container image: {container_image_name}")
        container_command = json.loads(
            os.getenv("JOB_COMMAND", '["sh", "-c"]'))
        print(f"Using container command: {container_command}")
        container_arguments = json.loads(os.getenv(
            "JOB_ARGS", f'["pip install requests && python {job_script_mount_path}/{job_script}"]'))
        print(f"Using container arguments: {container_arguments}")
        container_env: list = json.loads(os.getenv(
            "JOB_ENV", '[{"name": "DATA", "value": "Data is Here!!!!"}, {"name": "TELEGRAM_BOT_TOKEN", "secret": {"name": "nick-test", "key": "TELEGRAM_TOKEN"}}, {"name": "TELEGRAM_CHAT_ID", "secret": {"name": "nick-test", "key": "TELEGRAM_CHANNEL"}}]'))
        print(f"Using container environment variables: {container_env}")

        if app_annotations:
            for k, v in app_annotations.items():
                container_env.append({"name": k, "value": v})

        batch_v1 = client.BatchV1Api()

        job = client.V1Job(
            api_version="batch/v1",
            kind="Job",
            metadata=client.V1ObjectMeta(
                name=f"{app_name}-job", namespace=job_namespace),
            spec=client.V1JobSpec(
                ttl_seconds_after_finished=1,
                completions=1,
                backoff_limit=2,
                template=client.V1PodTemplateSpec(
                    spec=client.V1PodSpec(
                        restart_policy="OnFailure",
                        containers=[
                            client.V1Container(
                                name=f"{app_name}-job",
                                image=container_image_name,
                                command=container_command,
                                args=container_arguments if container_arguments else None,
                                volume_mounts=[
                                    V1VolumeMount(
                                        name="configmap-volume",
                                        mount_path=job_script_mount_path
                                    )
                                ],
                                env=build_env_vars(container_env, app_name)
                            )
                        ],
                        volumes=[
                            V1Volume(
                                name="configmap-volume",
                                config_map=V1ConfigMapVolumeSource(
                                    name=job_script_cm
                                )
                            )
                        ]
                    )
                )
            )
        )

        try:
            resp = batch_v1.create_namespaced_job(
                namespace=job_namespace, body=job)
            print(
                f"Job '{app_name}-job' created in namespace '{job_namespace}'")
            return resp
        except client.ApiException as e:
            print(f"Failed to create job - '{app_name}-job': {e}")
    except Exception as e:
        print(f"Error creating job for {app_name}: {e}")
        return None


def build_env_vars(raw_env: list, app_name: str = "default-app") -> list:
    if not raw_env:
        return []

    env_vars = []
    for item in raw_env:
        if "value" in item:
            env_vars.append(V1EnvVar(name=item["name"], value=str(item["value"])))
        elif "secret" in item:
            env_vars.append(V1EnvVar(
                name=item["name"],
                value_from=V1EnvVarSource(
                    secret_key_ref=V1SecretKeySelector(
                        name=item["secret"]["name"],
                        key=str(item["secret"]["key"])
                    )
                )
            ))
    env_vars.append(V1EnvVar(name="APP_NAME", value=app_name))
    return env_vars


def should_delete(file_age: int, created: int, deleted: int) -> bool:
    return (
        (
            created == 0
            or deleted == 0
        )
        and file_age > AGE_THRESHOLD_SECONDS
    )


def should_run_job(file_age: int, created: int, deleted: int) -> bool:
    """Check if conditions to run job are met."""
    return (
        AGE_THRESHOLD_SECONDS < file_age <= OVER_AGE_THRESHOLD_SECONDS
        and created == deleted
        or (
            deleted > 0
            and file_age > OVER_AGE_THRESHOLD_SECONDS
        )
    )


def handle_lock_file(lock_path):
    """Process a single lock file and decide action."""
    try:
        with open(lock_path, 'r') as f:
            data = json.load(f)
    except Exception as e:
        print(f"Error: Failed to read {lock_path}: {e}")
        return

    app_name = data.get("app_name", "unknown")
    timestamp = data.get("timestamp", 0)
    created = data.get("created", 0)
    deleted = data.get("deleted", 0)
    app_annotations = data.get("app_annotations", {})
    age = int(time()) - timestamp

    print(f"app: {app_name} age: {age}s | created: {created}, deleted: {deleted}")

    if should_delete(age, created, deleted):
        try:
            os.remove(lock_path)
            print(f"Deleted lock file: {lock_path}")
        except Exception as e:
            print(f"Error: Failed to delete {lock_path}: {e}")
    elif should_run_job(age, created, deleted):
        try:
            os.remove(lock_path)
            print(f"Running job for: {app_name}")
            create_jobs(app_name, app_annotations)
        except Exception as e:
            print(f"Error: Failed to delete {lock_path}: {e}")
    else:
        print(f"✅ No action needed for: {app_name}")


def schedular_job():
    """Scheduled job to process all lock files."""
    print("Running scheduled job...")

    lock_files = [f for f in os.listdir(LOCK_FILE_DIR) if f.endswith('.json')]

    if len(lock_files) == 0:
        print("No lock files to process.")
        return

    for lock_file in lock_files:
        handle_lock_file(os.path.join(LOCK_FILE_DIR, lock_file))


def initial():
    print("Initializing Kubernetes configuration...")
    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()

    print("Kubernetes configuration loaded successfully.")


if __name__ == "__main__":
    initial()

    # Schedule the job every 10 seconds
    schedule.every(10).seconds.do(schedular_job)

    while True:
        # Run pending jobs
        schedule.run_pending()
        # Sleep for a short duration to avoid busy waiting
        sleep(1)  # Adjust the sleep duration as needed
