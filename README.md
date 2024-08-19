# Part Lookup Flask Application

This is a simple Flask web application that allows users to look up a part name by entering its serial number. The application connects to a SQL Server database to retrieve the part name associated with the provided serial number.

## Requirements

- Python 3.x
- Flask
- pyodbc

## Installation

1. **Clone the repository** (if applicable) or download the source code.

2. **Set up the Python environment**:
    ```bash
    python -m venv venv
    ```

3. **Activate the virtual environment**:
   - On Windows:
     ```bash
     venv\Scripts\activate
     ```
   - On macOS/Linux:
     ```bash
     source venv/bin/activate
     ```

4. **Install the required Python packages**:
    ```bash
    pip install Flask pyodbc
    ```

## Database Configuration

Ensure that your SQL Server is set up correctly with the following details:

- **Server**: `DESKTOP-AKL5BJR`
- **Database**: `Incoming2818`
- **Table**: `[dbo].[Incoming]`
- **Connection**: Trusted Connection

The application queries the `Part#` from the `[dbo].[Incoming]` table where the `SN#` matches the serial number input by the user.

## Usage

1. **Run the Flask application**:
    ```bash
    python app.py
    ```

2. **Access the application**:
   Open your web browser and go to `http://localhost:5000`.

3. **Using the Application**:
   - Enter a serial number into the input field.
   - Click the "Lookup" button.
   - If the serial number exists in the database, the corresponding part name will be displayed.
   - If the serial number is not found, an alert will notify you that no part was found with that serial number.

## Code Explanation

- **Database Connection**: The application uses `pyodbc` to connect to the SQL Server database using the provided connection string.

- **Routing**: The main route (`/`) handles both `GET` and `POST` requests. On a `POST` request, it retrieves the serial number entered by the user, queries the database for the corresponding part name, and displays the result.

- **HTML and Bootstrap**: The web page is rendered using `render_template_string`, which includes a simple HTML form styled with Bootstrap for a clean UI.

## Customization

- **Database Connection String**: If you are deploying this application on a different server or database, modify the `connection_string` in the `app.py` file accordingly.
  
- **Port and Host**: The application is configured to run on port `5000` and is accessible from any host (`0.0.0.0`). You can modify these settings in the `app.run()` function.

## Troubleshooting

- **Database Connection Issues**: Ensure that your SQL Server is running, and the connection details in the `connection_string` are correct.
- **Port Conflicts**: If port `5000` is in use, you can change the port in the `app.run()` command.

