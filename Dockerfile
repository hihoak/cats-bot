FROM python:3.10

RUN mkdir /app
WORKDIR /app
COPY . /app
RUN python -m pip install --upgrade pip && pip install -r requirements.txt

CMD ["python3", "each_morning_cute.py"]
