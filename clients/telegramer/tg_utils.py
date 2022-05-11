import schedule


def job_to_str(job: schedule.Job):
    if job.interval == 1:
        return f"Каждый день в {job.at_time}"
    return f"Каждые {job.interval} дней в {job.at_time}"