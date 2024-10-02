import pandas as pd
from flask import Flask, request, render_template_string
from flask_sqlalchemy import SQLAlchemy
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)

app = Flask(__name__)

# Database configuration
app.config['SQLALCHEMY_DATABASE_URI'] = ''
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

class ReceivingLog(db.Model):
    __tablename__ = 'receiving_log'
    serial_number = db.Column(db.String(255), primary_key=True)
    entry_date = db.Column(db.Date)
    invoice_number = db.Column(db.String(255))
    box_number = db.Column(db.String(255))
    pod_number = db.Column(db.String(255))
    part_number = db.Column(db.String(255))
    quantity = db.Column(db.Float)

def load_data():
    file_path1 = r"C:\Users\Admin\OneDrive\Desktop\Incoming\Receiving Log_July_2024.xlsm"
    file_path2 = r"C:\Users\Admin\OneDrive\Desktop\Incoming\Receiving Log.xlsx"
    
    data1 = pd.read_excel(file_path1)
    data2 = pd.read_excel(file_path2)
    data = pd.concat([data1, data2], ignore_index=True)
    data['QTY'] = data['QTY'].fillna(1)

    data.rename(columns={
    'Date': 'entry_date',  
    'Inv# ': 'invoice_number',
    'Box #': 'box_number',
    'POD#': 'pod_number',
    'Part#': 'part_number',
    'SN#': 'serial_number',
    'QTY': 'quantity'
}, inplace=True)


    # Insert the data into the PostgreSQL table
    data.to_sql('receiving_log', db.engine, if_exists='replace', index=False)

@app.route('/', methods=['GET', 'POST'])
def index():
    serial_number = request.form.get('serial_number', '')
    found_entry = ReceivingLog.query.filter_by(serial_number=serial_number).first()
    if found_entry:
        part_name = found_entry.part_number
        message = "Part Found!"
        found = True
    else:
        part_name = ""
        message = "No part found with that serial number."
        found = False

    html = '''
    <!DOCTYPE html>
    <html>
    <head>
        <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css" rel="stylesheet">
        <link rel="icon" type="image/x-icon" href="{{ url_for('static', filename='favicon.ico') }}">
        <style>
            .container { max-width: 600px; margin-top: 50px; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1 class="mb-3">Lookup Part Name by Serial#</h1>
            <form method="post" class="mb-3">
                <div class="input-group mb-3">
                    <input type="text" class="form-control" placeholder="Enter Serial Number" name="serial_number" value="{{ serial_number }}">
                    <button class="btn btn-primary" type="submit">Lookup</button>
                </div>
            </form>
            {% if found %}
            <div class="alert alert-success">
                Serial Number: <span>{{ serial_number }}</span> <br> Part Name: <span>{{ part_name }}</span>
            </div>
            {% elif message %}
            <div class="alert alert-warning">{{ message }}</div>
            {% endif %}
        </div>
    </body>
    </html>
    '''
    return render_template_string(html, serial_number=serial_number, part_name=part_name, found=found, message=message)

if __name__ == '__main__':
    with app.app_context():
        db.create_all()  
        load_data()  
    app.run(host='0.0.0.0', port=5000)






