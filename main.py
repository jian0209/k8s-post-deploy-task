import kopf
from kubernetes import config
from time import time
import json
import os
import datetime
import ast

LOCK_FILE_DIR = "kopf-locks"
TRIGGER_ANNOTATION_KEY = "kopf.sh/post-deploy"
TRIGGER_ANNOTATION_VALUE = "true"
AGE_THRESHOLD_SECONDS = 120


@kopf.on.probe(id='now')
def get_current_timestamp(**kwargs):
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


@kopf.on.startup()
def initial(settings: kopf.OperatorSettings, **_):
    os.makedirs(LOCK_FILE_DIR, exist_ok=True)
    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()


@kopf.on.create('', 'v1', 'pods', annotations={TRIGGER_ANNOTATION_KEY: TRIGGER_ANNOTATION_VALUE})
def handle_pod_create(body, spec, meta, status, logger, **kwargs):
    try:
        app_annotations: dict | None = {}

        app_name = meta.get("labels", {}).get("app")
        pod_hash = meta.get("labels", {}).get("pod-template-hash")
        pod_name = meta.get("name")
        pod_container_image = spec.get("containers", [])[
            0].get("image", "unknown")

        if os.getenv("KUBE_ANNOTATIONS"):
            kube_annotations_str = os.getenv("KUBE_ANNOTATIONS")
            kube_annotations = json.loads(kube_annotations_str)
            if isinstance(kube_annotations, list):
                print(f"KUBE_ANNOTATIONS: {kube_annotations}")
                for annotation in kube_annotations:
                    try:
                        app_annotation_str: str = meta.get("annotations", {}).get(f"kopf.sh/{annotation}")
                        if not app_annotation_str:
                            raise KeyError()
                        try:
                            app_annotation = ast.literal_eval(app_annotation_str)
                        except (ValueError, SyntaxError):
                            app_annotation = app_annotation_str
                        app_annotations[annotation] = app_annotation
                    except KeyError:
                        print(f"Warning: Annotation '{annotation}' not found in pod metadata.")
            else:
                print("Warning: Invalid KUBE_LABEL format, expected a list.")
                app_annotations = None

        print("========= create start =========")
        print(f"app_name ===> {app_name}")
        print(f"pod_hash ===> {pod_hash}")
        print(f"pod_name ===> {pod_name}")
        print(f"pod_container_image ===> {pod_container_image}")
        print(f"app_annotations ===> {app_annotations}")
        print("========= create end =========")

        lock_file_path = f"{LOCK_FILE_DIR}/{app_name}.json"

        existed_data = read_lock_file(lock_file_path)
        if existed_data is None:
            data = {
                "app_name": app_name,
                "pod_hash": pod_hash,
                "pod_name": pod_name,
                "created": 1,
                "deleted": 0,
                "timestamp": int(time())
            }
            if app_annotations:
                data["app_annotations"] = app_annotations
        else:
            data = existed_data
            data["created"] += 1
            data["timestamp"] = int(time())

        add_lock_file(lock_file_path, data)
        print(
            f"Lock file created for {app_name} with generateName: {pod_hash}")
    except Exception as e:
        print(f"Error handling pod creation: {e}")
        return


@kopf.on.delete('', 'v1', 'pods', annotations={TRIGGER_ANNOTATION_KEY: TRIGGER_ANNOTATION_VALUE})
def handle_pod_delete(body, spec, meta, status, logger, **kwargs):
    try:
        app_name = meta.get("labels", {}).get("app")
        pod_hash = meta.get("pod-template-hash")
        pod_name = meta.get("name")
        pod_container_image = spec.get("containers", [])[
            0].get("image", "unknown")

        print("========= delete start =========")
        print(f"app_name ===> {app_name}")
        print(f"pod_hash ===> {pod_hash}")
        print(f"pod_name ===> {pod_name}")
        print(f"pod_container_image ===> {pod_container_image}")
        print("========= delete end =========")

        lock_file_path = f"{LOCK_FILE_DIR}/{app_name}.json"

        if os.path.exists(lock_file_path):
            existed_data = read_lock_file(lock_file_path)
            if existed_data is not None:
                if "deleted" in existed_data:
                    existed_data["deleted"] += 1
                else:
                    existed_data["deleted"] = 1

                existed_data["timestamp"] = int(time())

                add_lock_file(lock_file_path, existed_data)
                print(
                    f"Lock file updated for {app_name} with delete count.")
            else:
                print(f"Lock file for {app_name} exists but is empty.")
        else:
            print(
                f"Lock file for {app_name} does not exist. but pod is deleted.")
    except Exception as e:
        print(f"Error handling pod deletion: {e}")
        return


def add_lock_file(file_path, data):
    try:
        with open(file_path, "w") as lock_file:
            lock_file.write(f"{json.dumps(data)}")
            lock_file.close()
    except Exception as e:
        print(f"Error writing lock file: {e}")
        return


def read_lock_file(file_path):
    try:
        with open(file_path, "r") as lock_file:
            return json.load(lock_file)
    except Exception as e:
        print(f"Error reading lock file: {e}")
        return None
