FROM python:3.7
ADD gira.py /
ADD requirements.txt /
RUN pip install -r /requirements.txt
RUN mkdir /code
VOLUME /code
WORKDIR /code
ENTRYPOINt [ "python", "/gira.py" ]
