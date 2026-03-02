from painted import show

data = {
    "service": "api-gateway",
    "version": "2.4.1",
    "replicas": {"desired": 3, "ready": 3},
}
show(data)
