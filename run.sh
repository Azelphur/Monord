#!/bin/bash

echo "Waiting for PostgreSQL"
./wait-for-it.sh monord_db:5432
echo "Waiting for Elasticsearch"
./wait-for-it.sh monord_es:9200
echo "Updating/creating DB schema"
alembic upgrade head
echo "Starting Monord"
python -u run.py

