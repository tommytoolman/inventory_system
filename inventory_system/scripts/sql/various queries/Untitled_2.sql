SELECT platform_name, sync_status, COUNT(*) 
FROM platform_common 
GROUP BY platform_name, sync_status;