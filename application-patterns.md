Definition and design of application patterns.

By codifying functional/ non-functional requirements, security controls, resiliency, performance, operational capabilities, scalability, and automated deployment of pattern instances in a pre-approved form.

1: Functional requirements: what infrastructure services are used by an application instance? How is data stored and processed? How are users and other applications accessing the application or its underlined data?

2: Non-functional requirements, how data is secured, including risk and threat models; how the application performs, including SLAs; how the application scales; how the application fails

3: Configuration parameters of an instance of a pattern 

4: On the boarding process, how many new users for the pattern will create a new instance? 

5: Pattern boot process what one-time resources are created and used by the incense of this pattern. What GCP resources would be activated in order to enabled 

6: Instant boot process: what is the process for creating a new instance of this pattern 

7: Deployment model: how does the application and its components are deployed within an instance of a pattern. How would we use Terri to accomplish this goal? 

8: Threat model - Threat vectors exist on this instance of the pattern?

9: Control or security controls are used to control, threats vectors, including axis, control, encryption, and threat prevention.

10: Compliance rules what proof is there what proof is used to ensure there are controls that are configured correctly before, and after the app deploy the app, in an instance of a pattern.￼

By structuring the components in this manner, we ensure clarity and comprehensiveness in detailing the various aspects of the GCP Application Patterns. We will iterate and shape this guide to serve as a robust guide for developers and architects in understanding, implementing, and maintaining the pattern effectively.

Anatomy of a GCP Batch Data Pattern v1
1: Functional Requirements - Add jobs to queues. Notified when job is completed. Ability to define job dependencies. Specify resources required by a job (CPU, memory). Support for submitting shell scripts as batch jobs. VM or Container based jobs. Reprocess failed job events. Standardized IdP backed roles Admin, User, Audit.

2: Non-Functional Requirements - Dashboard for Admin role with metrics related to batch jobs status, review failed jobs, and job history. 5+ Standard alarms. Queues with priorities to allow jobs that needs to run immediately take precedence. Batch worker environment is destroyed once the job is completed reducing cost. Time based and/or data event-based trigger of batch jobs.

3: Configuration - Choice of VM or Container based jobs. Job queues with configurable priorities. Specify resources required by a job (CPU, memory).

4: Onboarding process - Instantiate published module + ref location in central infrastructure lib. Wiki documentation for pattern.

5: Pattern Boot - Create standardized IdP backed roles Admin, User, Audit accessible to the pattern. Initialize Log location. Initialize standard monitoring metrics and alarms.

6: Instance Boot - Version check. Setup log instance. Setup monitoring.

7: Deployment model - Git based template for CI/CD build/deployment.

8: Threat model - Threat vectors???

9: Controls - Standardized IdP backed roles Admin, User, Audit. Node encryption with Customer Managed Keys. Authentication is required for image registry access.

10: Compliance - Continuous image scanning for patch/ vulnerability compliance. Continuous monitoring checks with audit logs. Regular review of access logs for suspicious activity. Policy as Code compliance.

Anatomy of a GCP Stream Data Pattern v1
1: Functional Requirements - Support multiple streaming data sources Durable message-transport service Pipeline-based programming to process streaming data. Processed events are stored as single, consistent, time-series representations Managed rules engine supporting Beam or Presto and 30 more open source tools and frameworks Notify users of job completion, failures, and warnings. Standardized based roles Admin, User, Audit

2: Non-Functional Requirements - Late and out-of-order data processing using watermarks from timestamped events. Fixed, Sliding, Session windowing. Process messages in fie order it was received Dashboard for Admin/User role with metrics related to stream data health
10+ Standard alarms. Developer-focused business rules engine with rules defined in JSON (v2). Supports Java and Python programming language for rules implementation

3: Configuration - Multi-zone in single region or single zone. Process the messagees in the order receved. Message deduplication for exactly one messge processing.

4: Onboarding Process - Instatitate published module + ref location in central infrastruare libraries. Git repo's README and Confluence for documentation for pattern and software components.

5: Pattern Boot - Create sandardized identity provider (IdP) backed roles Admin, User, Audit accessible to the pattarn. Initalize standard montioring metrics and alarms.

6: Instance Boot - Version check. Setup log instance. Setup monitoring

7: Deployment Model - Git based template for CVCD build/deployment. Reprocess failed stream events.

8: Threat Model - Threat vectors in control plane, pod and node.

9: Controls - Standardized identity provider (IdP) baked roles Admin, User, Audit. Envelope encrypton of Secrets with KMS

10: Compliance - Contiunus monitoring checks with audit logs, alerts, and dashboards.
