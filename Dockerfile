FROM python:3.10                                                                                                     
                                                                                                                    
WORKDIR /app                                                                                                         
                                                                                                                    
COPY requirements.txt requirements.txt                                                                               
RUN pip install --no-cache-dir -r requirements.txt                                                                   
                                                                                                                    
COPY populate-and-update-influxdb.py populate-and-update-influxdb.py                                                 
COPY example.env .env                                                                                                
                                                                                                                    
CMD ["python3", "populate-and-update-influxdb.py"]