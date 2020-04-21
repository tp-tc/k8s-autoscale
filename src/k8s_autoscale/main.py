import os.path
import time

import kubernetes
import yaml
from taskcluster import Queue

from k8s_autoscale.logging import get_logger
from k8s_autoscale.sla import get_new_worker_count

logger = get_logger()


def autoscale(config):
    config = yaml.safe_load(config)
    while True:
        for worker_type in config["worker_types"]:
            # TODO: run in parallel
            handle_worker_type(worker_type)
        logger.info("Sleeping between polls")
        time.sleep(180)


def get_api(kube_config, kube_config_context):
    if kube_config and kube_config_context:
        logger.info("Using kube config")
        api_client = kubernetes.config.new_client_from_config(
            config_file=os.path.expanduser(kube_config), context=kube_config_context
        )
    else:
        logger.info("Using in-cluster config")
        api_client = kubernetes.config.load_incluster_config()
    api = kubernetes.client.AppsV1beta2Api(api_client=api_client)
    return api


def get_deployment_status(api, deployment_namespace, deployment_name):
    return api.read_namespaced_deployment(
        name=deployment_name, namespace=deployment_namespace
    ).status


def get_running(api, deployment_namespace, deployment_name):
    return get_deployment_status(api, deployment_namespace, deployment_name).ready_replicas or 0


def adjust_scale(api, target_replicas, deployment_namespace, deployment_name):
    # "add" works as "replace" in case we have more than 0 replicas.
    # "replace" fails in case we don't have any replicas running
    patch = [{"op": "add", "path": "/spec/replicas", "value": target_replicas}]
    logger.debug("PATCH object", patch=patch)
    api.patch_namespaced_deployment_scale(
        name=deployment_name, namespace=deployment_namespace, body=patch
    )


def handle_worker_type(cfg):
    min_replicas = cfg["autoscale"]["args"]["min_replicas"]
    log = logger.bind(
        worker_type=cfg["worker_type"],
        provisioner=cfg["provisioner"],
        deployment_namespace=cfg["deployment_namespace"],
        deployment_name=cfg["deployment_name"],
        min_replicas=min_replicas,
    )
    api = get_api(cfg.get("kube_connfig"), cfg.get("kube_connfig_context"))
    log.info("Handling worker type. Getting the number of running replicas...")
    running = get_running(
        api=api,
        deployment_namespace=cfg["deployment_namespace"],
        deployment_name=cfg["deployment_name"],
    )
    log = log.bind(running=running)
    log.info("Calculating capacity")
    max_replicas = cfg["autoscale"]["args"]["max_replicas"]
    min_replicas = cfg["autoscale"]["args"]["min_replicas"]
    log = log.bind(max_replicas=max_replicas, min_replicas=min_replicas)

    log.info("Checking pending")
    queue = Queue({"rootUrl": cfg["root_url"]})
    pending = queue.pendingTasks(cfg["provisioner"], cfg["worker_type"])["pendingTasks"]
    log = log.bind(pending=pending)
    log.info("Calculated desired replica count")
    target_replicas = get_new_worker_count(pending, running, cfg["autoscale"]["args"])
    target_replicas = max(min(target_replicas, max_replicas), min_replicas)
    log = log.bind(target_replicas=target_replicas)
    if target_replicas == running:
        log.info("Zero replicas needed")
    else:
        if target_replicas < running:
            log.info(f"Need to remove {running-target_replicas} of {running}")
        else:
            log.info(f"Need to increase capacity from {running} running by {target_replicas-running}")
        adjust_scale(api, target_replicas, cfg["deployment_namespace"], cfg["deployment_name"])
    log.info("Done handling worker type")
