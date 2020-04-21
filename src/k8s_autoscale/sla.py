import math


def get_new_worker_count(pending, running, args):
    # TODO: verify all the args
    assert args["sla_seconds"] > args["avg_task_duration"]
    # In case we don't want to cover all the pending tasks
    pending = int(math.ceil(pending * args["capacity_ratio"]))
    # Assume that all running workers have a task
    outstanding = pending + running
    # How many tasks a replica can process within our tolerance period
    tasks_per_replica = math.floor(args["sla_seconds"] / args["avg_task_duration"])
    # how many tasks can be covered by the running replicas, assuming they are
    # busy and can only take new tasks after they are done with the current one
    needed_replicas = math.ceil(outstanding / tasks_per_replica)
    return needed_replicas
