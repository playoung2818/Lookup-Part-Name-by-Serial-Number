from flask import Flask, request, render_template_string
import pyodbc

app = Flask(__name__)

# Your database connection string
connection_string = ''

# Route to handle the web page
@app.route('/', methods=['GET', 'POST'])
def index():
    serial_number = ""  # Default empty value for serial number
    part_name = ""  # Default empty value for part name
    message = ""
    found = False  # Flag to check if the part is found
    if request.method == 'POST':
        serial_number = request.form['serial_number']
        # Connect to the database
        with pyodbc.connect(connection_string) as conn:
            cursor = conn.cursor()
            # Query to fetch the part name using the serial number
            cursor.execute("SELECT Part# FROM [dbo].[Incoming] WHERE SN# = ?", (serial_number,))
            result = cursor.fetchone()
            if result:
                part_name = result[0]
                found = True
            else:
                message = "No part found with that serial number."

    # HTML form for input, now using Bootstrap for styling
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
    app.run(host='0.0.0.0', port=5000)






