WITH tables_scanned AS (
  SELECT
  event_timestamp,
  JSON_VALUE(payload,'$.authenticationInfo.principalEmail') AS email,
  JSON_VALUE(payload,'$.metadata.jobChange.job.jobName')  AS job_name,
  JSON_VALUE(payload,"$.metadata.jobChange.job.jobConfig.queryConfig.destinationTable") AS target_table
  
  FROM `bigquery_audit_logs.cloudaudit_googleapis_com_data_access`
  
  WHERE IFNULL(JSON_EXTRACT(payload,'$.metadata.jobChange'),"") != ""
),

fields_scanned AS (
  SELECT
  JSON_VALUE(payload,"$.metadata.tableDataRead.jobName")  AS job_name,
  JSON_VALUE(payload,"$.resourceName"),
  fields as source_field, 
  JSON_VALUE(payload,"$..resourceName") as source_table
  
  FROM `bigquery_audit_logs.cloudaudit_googleapis_com_data_access`
  
  CROSS JOIN UNNEST(JSON_EXTRACT_ARRAY(payload,"$.metadata.tableDataRead.fields")) as fields
  
  WHERE  IFNULL(JSON_EXTRACT(payload,"$.metadata.tableDataRead"),"") != ""
)

SELECT
event_timestamp,
job_name,
ts.email, 
fs.source_table,
fs.source_field,
ts.target_table

FROM tables_scanned ts

INNER JOIN fields_scanned fs USING(job_name)