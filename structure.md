osint_system/
├── config/
│   ├── settings.py                 # General application settings (e.g., API keys, rate limits)
│   ├── agent_configs.py            # Configuration specific to each agent type (e.g., prompts, model names)
│   └── source_configs.py           # Configuration for data sources (e.g., URLs, API endpoints, scraping rules)
├── agents/
│   ├── __init__.py
│   ├── base_agent.py               # Base class for all agents
│   ├── planning_agent.py           # Logic for the Planning/Orchestration Agent
│   ├── crawlers/
│   │   ├── __init__.py
│   │   ├── base_crawler.py         # Base class for crawler agents
│   │   ├── newsfeed_agent.py       # Specific crawler for news feeds
│   │   ├── social_media_agent.py   # Specific crawler for social media
│   │   └── document_scraper_agent.py # Specific crawler for documents
│   └── sifters/
│       ├── __init__.py
│       ├── base_sifter.py          # Base class for sifter agents
│       ├── fact_extraction_agent.py# Agent for identifying and extracting facts
│       ├── fact_classification_agent.py # Agent for categorizing facts
│       ├── verification_agent.py   # Agent for resolving dubious facts
│       └── analysis_reporting_agent.py # Agent for synthesizing analysis and reports
├── data_management/
│   ├── __init__.py
│   ├── data_store.py               # Handles interactions with the central data store (e.g., database, file system)
│   ├── preprocessor.py             # Contains text pre-processing functions (e.g., HTML removal, normalization)
│   └── metadata_handler.py         # Manages the capture and preservation of data metadata
├── utils/
│   ├── __init__.py
│   ├── llm_utils.py                # Utilities for LLM interactions (e.g., prompt templates, function calling wrappers)
│   ├── communication_protocols.py  # Implementations for MCP and A2A communication
│   ├── error_handling.py           # Centralized error handling and logging
│   └── evaluation_metrics.py       # Tools for defining and calculating evaluation metrics
├── tools/                          # External tools/APIs that agents can call (via MCP)
│   ├── __init__.py
│   ├── web_scraper.py              # Generic web scraping functionality
│   ├── api_interface.py            # Common interface for interacting with various external APIs
│   ├── search_engine_tool.py       # Wrapper for targeted search engine queries
│   └── database_connector.py       # Logic for querying structured databases
├── main.py                         # Entry point for the application, initializes agents and orchestrates the workflow
├── requirements.txt                # Python dependencies
├── README.md                       # Project documentation (already exists)
└── tests/                          # Unit and integration tests
    ├── __init__.py
    ├── agents/
    ├── data_management/
    └── utils/
