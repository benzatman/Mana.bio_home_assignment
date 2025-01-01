from flask import Flask, request, render_template, jsonify
import pandas as pd
import sqlite3
import os
from statistics import mean, median, stdev
import traceback

app = Flask(__name__)
DATABASE = 'results.db'
UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# Initialize SQLite database
def init_db():
    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()
        cursor.execute('''CREATE TABLE IF NOT EXISTS results (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            experiment_type TEXT,
                            formulation_id TEXT,
                            calculated_value REAL,
                            valid BOOLEAN,
                            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
        conn.commit()

init_db()

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload():
    file = request.files.get('file')
    if not file:
        return jsonify({'error': 'No file uploaded'}), 400

    filepath = os.path.join(UPLOAD_FOLDER, file.filename)
    file.save(filepath)

    try:
        experiment_type, results = process_file(filepath)
        store_results(experiment_type, results)
        return jsonify({'message': 'File processed and results stored successfully, go to main page to view results'}), 200
    except Exception as e:
        tb = traceback.format_exc()
        return jsonify({
            'error': str(e),
            'traceback': tb
        }), 500
    

@app.route('/results')
def results():
    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()
        cursor.execute('SELECT DISTINCT experiment_type FROM results')
        experiment_types = cursor.fetchall()
        return render_template('results.html', experiment_types=[x[0] for x in experiment_types])

@app.route('/results/<experiment_type>')
def experiment_results(experiment_type):
    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()
        cursor.execute('''SELECT formulation_id, calculated_value FROM results 
                          WHERE experiment_type = ?''', (experiment_type,))
        rows = cursor.fetchall()

    values = [x[1] for x in rows]
    stats = {
        'median': median(values),
        'average': mean(values),
        'std_dev': stdev(values)
    }

    return render_template('experiment_results.html', rows=rows, stats=stats, experiment_type=experiment_type)

def process_file(filepath):
    if filepath.endswith('.xlsx'):
        data = pd.read_excel(filepath)
    elif filepath.endswith('.csv'):
        data = pd.read_csv(filepath)
    else:
        raise ValueError('Unsupported file format')

    if 'Measurement Type' in data.columns:  # Zeta Potential file logic
        return 'Zeta Potential', process_zeta_potential(data)
    else:  # TNS logic assumed
        return 'TNS', process_tns(data)

def process_tns(data):
    results = []
    for row in range(1, data.shape[0]):
        formulation_id = data.iloc[row, 0]
        triplicate_values = data.iloc[row, 1:4]
        control_values = data.iloc[row, 8:12]
        
        avg_formulation = triplicate_values.mean()
        avg_control = control_values.mean()
        calculated_value = avg_formulation / avg_control

        results.append({
            'formulation_id': formulation_id,
            'calculated_value': calculated_value,
            'valid': calculated_value > 10
        })
    return results

def process_zeta_potential(data):
    results = []

    # Remove rows with NaN in the 'Sample Name' column
    data = data.dropna(subset=['Sample Name'])

    # Ensure 'Zeta Potential (mV)' is numeric
    data['Zeta Potential (mV)'] = pd.to_numeric(data['Zeta Potential (mV)'], errors='coerce')

    # Filter controls and calculate the mean of the control zeta potential
    control_values = data[data['Sample Name'].str.startswith('STD')]['Zeta Potential (mV)']
    avg_control = control_values.mean()

    # Handle invalid control values
    if pd.isnull(avg_control) or avg_control == 0:
        raise ValueError("Invalid control values: Cannot calculate mean. Ensure controls are numeric and non-zero.")

    # Process formulations
    formulations = data[~data['Sample Name'].str.startswith('STD')]
    for _, row in formulations.iterrows():
        formulation_id = row['Sample Name']
        zeta_value = row['Zeta Potential (mV)']

        # Ensure zeta_value is numeric
        if pd.isnull(zeta_value):
            print(f"Skipping {formulation_id}: Non-numeric zeta value found")
            continue

        # Normalize by control average
        calculated_value = zeta_value / avg_control

        results.append({
            'formulation_id': formulation_id,
            'calculated_value': calculated_value,
            'valid': calculated_value > 0  # Results must be positive
        })

    return results



def store_results(experiment_type, results):
    with sqlite3.connect(DATABASE) as conn:
        cursor = conn.cursor()
        for result in results:
            cursor.execute('''INSERT INTO results (experiment_type, formulation_id, calculated_value, valid)
                              VALUES (?, ?, ?, ?)''',
                           (experiment_type, result['formulation_id'], result['calculated_value'], result['valid']))
        conn.commit()

if __name__ == '__main__':
    app.run(debug=True)
