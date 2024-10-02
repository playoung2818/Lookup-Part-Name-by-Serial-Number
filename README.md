# Part Lookup Flask Application

This is a simple Flask web application that allows users to look up a part name by entering its serial number. The application use Postgresql database to retrieve the part name associated with the provided serial number.

## ScreenShot

![image](https://github.com/user-attachments/assets/666b0afc-d8f3-40e8-907e-fe44fab87021)

## Requirements

- Python 
- Flask

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


