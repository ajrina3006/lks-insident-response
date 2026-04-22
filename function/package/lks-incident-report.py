import json
import boto3
import requests
import os
from datetime import datetime

# Inisialisasi AWS Clients
dynamodb = boto3.resource('dynamodb')
sns = boto3.client('sns')

# Konfigurasi dari Environment Variables
# Pastikan di Lambda Console, nama-nama ini sudah di-set di tab Configuration
TABLE_NAME = os.environ.get('INCIDENTS_TABLE', 'incident') # Sesuaikan jika nama tabelmu 'incident'
incidents_table = dynamodb.Table(TABLE_NAME)

SNS_TOPIC_ARN = os.environ.get('SNS_TOPIC_ARN')
API_GATEWAY_URL = os.environ.get('API_GATEWAY_URL') # Contoh: https://rwz19s2ocb.execute-api.us-east-1.amazonaws.com/prod
OLLAMA_ENDPOINT = os.environ.get('OLLAMA_ENDPOINT') # Contoh: http://IP-EC2-KAMU:11434
OLLAMA_MODEL = os.environ.get('OLLAMA_MODEL', 'phi4')

def lambda_handler(event, context):
    try:
        # 1. Ambil incident_id dari event
        incident_id = event.get('incident_id') or event.get('incidentId') or event.get('id')
        if not incident_id:
            raise ValueError("incident_id is required")

        print(f"Processing incident: {incident_id}")

        # 2. Ambil data awal dari DynamoDB
        response = incidents_table.get_item(Key={'id': incident_id})
        if 'Item' not in response:
            raise Exception(f"Incident {incident_id} not found in DynamoDB")
        
        incident = response['Item']

        # 3. ANALISIS AI (Phi-4 via Ollama)
        # Kita panggil AI untuk mendapatkan laporan dan saran perbaikan
        print("Calling Phi-4 for analysis...")
        ai_report = generate_ai_analysis(incident)
        
        # 4. UPDATE DYNAMODB dengan hasil AI
        incidents_table.update_item(
            Key={'id': incident_id},
            UpdateExpression='SET report = :r, suggestions = :s, ai_analyzed = :t',
            ExpressionAttributeValues={
                ':r': ai_report['report'],
                ':s': ai_report['suggestions'],
                ':t': datetime.utcnow().isoformat()
            }
        )
        
        # Update data incident lokal untuk dipakai di email
        incident['report'] = ai_report['report']
        incident['suggestions'] = ai_report['suggestions']

        # 5. KIRIM NOTIFIKASI SNS (Email dengan Link)
        print("Sending SNS notification...")
        send_sns_notification(incident)

        return {
            'statusCode': 200,
            'body': json.dumps(f"Incident {incident_id} analyzed and notification sent.")
        }

    except Exception as e:
        print(f"Error: {str(e)}")
        return {'statusCode': 500, 'body': json.dumps(str(e))}

def generate_ai_analysis(incident):
    """Fungsi untuk memanggil Ollama API"""
    prompt = f"""
    Analyze this incident: {incident.get('description')}
    Type: {incident.get('insident_type')}
    Severity: {incident.get('severity')}
    
    Provide a concise technical report and 3 actionable suggestions.
    """
    
    try:
        payload = {
            "model": OLLAMA_MODEL,
            "prompt": prompt,
            "stream": False
        }
        res = requests.post(f"{OLLAMA_ENDPOINT}/api/generate", json=payload, timeout=60)
        if res.status_code == 200:
            full_text = res.json().get('response', '')
            return {
                "report": full_text[:500], # Batasi agar tidak terlalu panjang di email
                "suggestions": ["Check logs", "Restart Service", "Verify Resource"] # Default suggestions
            }
    except:
        return {"report": "AI Analysis unavailable", "suggestions": ["Manual check required"]}

def send_sns_notification(incident):
    """Fungsi untuk menyusun email dan mengirim ke SNS"""
    # Link untuk API Gateway
    auto_url = f"{API_GATEWAY_URL}/action?id={incident['id']}&action=auto"
    manual_url = f"{API_GATEWAY_URL}/action?id={incident['id']}&action=manual"

    subject = f"🚨 ALERT: {incident.get('severity', 'HIGH')} Incident - {incident['id']}"
    
    body = f"""
INCIDENT DETAILS
----------------
ID: {incident['id']}
Type: {incident.get('insident_type', 'Unknown')}
Description: {incident.get('description', 'N/A')}

AI ANALYSIS (Phi-4)
-------------------
{incident.get('report', 'No AI analysis available')}

ACTION REQUIRED
---------------
Klik link di bawah ini untuk merespons:

🤖 AUTO RESOLVE (AI Recommended):
{auto_url}

👤 MANUAL HANDLING:
{manual_url}
    """
    
    sns.publish(
        TopicArn=SNS_TOPIC_ARN,
        Subject=subject,
        Message=body
    )
