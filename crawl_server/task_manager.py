from crawl_server.database import TaskManagerDatabase, Task, TaskResult
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import Manager
from apscheduler.schedulers.background import BackgroundScheduler
from datetime import datetime
from crawl_server.crawler import RemoteDirectoryCrawler
from crawl_server.callbacks import PostCrawlCallbackFactory


class TaskManager:

    def __init__(self, db_path, max_processes=2):
        self.db_path = db_path
        self.db = TaskManagerDatabase(db_path)
        self.pool = ProcessPoolExecutor(max_workers=max_processes)
        self.max_processes = max_processes
        manager = Manager()
        self.current_tasks = manager.list()

        scheduler = BackgroundScheduler()
        scheduler.add_job(self.execute_queued_task, "interval", seconds=1)
        scheduler.start()

    def put_task(self, task: Task):
        self.db.put_task(task)

    def get_tasks(self):
        return self.db.get_tasks()

    def get_current_tasks(self):
        return self.current_tasks

    def get_non_indexed_results(self):
        return self.db.get_non_indexed_results()

    def execute_queued_task(self):

        if len(self.current_tasks) <= self.max_processes:
            task = self.db.pop_task()
            if task:
                print("pooled " + task.url)
                self.current_tasks.append(task)

                self.pool.submit(
                    TaskManager.run_task,
                    task, self.db_path, self.current_tasks
                ).add_done_callback(TaskManager.task_complete)

    @staticmethod
    def run_task(task, db_path, current_tasks):
        result = TaskResult()
        result.start_time = datetime.utcnow()
        result.website_id = task.website_id

        print("Starting task " + task.url)

        crawler = RemoteDirectoryCrawler(task.url, 10)
        crawl_result = crawler.crawl_directory("./crawled/" + str(task.website_id) + ".json")

        result.file_count = crawl_result.file_count
        result.status_code = crawl_result.status_code

        result.end_time = datetime.utcnow()
        print("End task " + task.url)

        callback = PostCrawlCallbackFactory.get_callback(task)
        if callback:
            callback.run()
            print("Executed callback")

        return result, db_path, current_tasks

    @staticmethod
    def task_complete(result):

        try:
            task_result, db_path, current_tasks = result.result()
        except Exception as e:
            print("Exception during task " + str(e))
            return

        print(task_result.status_code)
        print(task_result.file_count)
        print(task_result.start_time)
        print(task_result.end_time)

        db = TaskManagerDatabase(db_path)
        db.log_result(task_result)
        print("Logged result to DB")

        for i, task in enumerate(current_tasks):
            if task.website_id == task_result.website_id:
                del current_tasks[i]

