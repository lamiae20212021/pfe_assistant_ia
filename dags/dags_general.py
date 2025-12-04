from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.bash import BashOperator
from pendulum import timezone

local_tz = timezone("Europe/Paris")

default_args = {
    'owner': 'Imane',
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
}


#  DAG combiné parallèle : IA + Santé

with DAG(
    dag_id='articles_global_dag',
    default_args=default_args,
    description='DAG combiné pour exécuter IA et Santé en parallèle chaque jour',
    schedule_interval='0 5 * * *',
    start_date=datetime(2025, 10, 31, tzinfo=local_tz),
    catchup=False,
    tags=['articles', 'ia', 'santé'],
) as dag:

    fetch_ai_articles = BashOperator(
        task_id='fetch_ai_articles',
        bash_command='python3 /opt/airflow/scripts/automatisation.py'
    )

    fetch_health_articles = BashOperator(
        task_id='fetch_health_articles',
        bash_command='python3 /opt/airflow/scripts/automatisation_santé.py'
    )

    # Exécution parallèle (aucune dépendance entre les deux)
    [fetch_ai_articles, fetch_health_articles]
