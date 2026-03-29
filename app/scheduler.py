import logging
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from threading import Lock

from app.database import db
from app.config_manager import config_manager
from app.syncer import syncer

logger = logging.getLogger(__name__)

class SchedulerManager:
    def __init__(self):
        self.scheduler = None
        self.job_id = "full_sync_job"
        self.lock = Lock()
    
    def start(self):
        try:
            if self.scheduler and self.scheduler.running:
                logger.warning("Scheduler already running")
                return
            
            self.scheduler = BackgroundScheduler()
            self.reload_job()
            self.scheduler.start()
            logger.info("Scheduler started")
        except Exception as e:
            logger.error(f"Failed to start scheduler: {e}")
    
    def stop(self):
        try:
            if self.scheduler and self.scheduler.running:
                self.scheduler.shutdown()
                logger.info("Scheduler stopped")
        except Exception as e:
            logger.error(f"Error stopping scheduler: {e}")
    
    def reload_job(self):
        try:
            with self.lock:
                if not self.scheduler:
                    return
                
                # Remove existing job
                try:
                    self.scheduler.remove_job(self.job_id)
                except Exception:
                    pass
                
                # Get config
                scheduler_config = db.get_scheduler_config()
                if not scheduler_config:
                    scheduler_config = {'enabled': False, 'cron_expr': '0 3 * * *'}
                
                if scheduler_config.get('enabled', False):
                    cron_parts = scheduler_config['cron_expr'].split()
                    if len(cron_parts) == 5:
                        trigger = CronTrigger(
                            minute=cron_parts[0],
                            hour=cron_parts[1],
                            day=cron_parts[2],
                            month=cron_parts[3],
                            day_of_week=cron_parts[4]
                        )
                        self.scheduler.add_job(
                            self._scheduled_sync,
                            trigger=trigger,
                            id=self.job_id,
                            replace_existing=True
                        )
                        logger.info(f"Scheduled job added: {scheduler_config['cron_expr']}")
                    else:
                        logger.error(f"Invalid cron expression: {scheduler_config['cron_expr']}")
                else:
                    logger.info("Scheduled sync is disabled")
        except Exception as e:
            logger.error(f"Error reloading job: {e}")
    
    def _scheduled_sync(self):
        try:
            logger.info("Starting scheduled full sync")
            # Update config before sync to get latest bwlimit
            sync_config = config_manager.get_sync_config()
            scheduler_config = db.get_scheduler_config()
            if scheduler_config and scheduler_config.get('bwlimit'):
                # Apply bandwidth limit if configured
                pass
            
            syncer.execute_full_sync(triggered_by='scheduled')
            logger.info("Scheduled full sync completed")
        except Exception as e:
            logger.error(f"Scheduled sync error: {e}")

scheduler_manager = SchedulerManager()
