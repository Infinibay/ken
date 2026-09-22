def retry(times, work):
    result = None
    for _ in range(times):
        result = work()
        if result:
            return result
    return result

def run(handler):
    return retry(3, handler)
