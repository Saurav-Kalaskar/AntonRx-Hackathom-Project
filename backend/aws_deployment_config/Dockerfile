# Use an official Python runtime as a parent image
FROM python:3.11-slim

# Set environment variables for Python
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set the working directory in the container
WORKDIR /app

# Copy the requirements file into the container
COPY aws_deployment_config/requirements.txt .

# Install dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the current directory contents into the container at /app
COPY . /app

# Expose the API port
EXPOSE 8005

# Command to run the FastApi application using Uvicorn (Assuming a main.py is created later, or adjust as needed)
# Since we don't have a main.py listed yet, we are preparing the environment. 
# CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8005"]
CMD ["python", "main.py"]
