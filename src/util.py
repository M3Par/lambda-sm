import json
from datetime import date, datetime, time


def echo_request(event):
    params = event['queryStringParameters'] or {}
    
    echo = ('echo_request' in params and
            event['stageVariables']['lambdaAlias'] == 'dev')
    
    if echo:
        del params['echo_request']
        del event['multiValueQueryStringParameters']['echo_request']
    
    return echo


def fetchone_to_dict(cursor):
    col_names = [ col[0] for col in cursor.description ]
    row = cursor.fetchone()
    
    if row:
        return dict(zip(col_names, row))


def fetchall_to_dict(cursor):
    col_names = [ col[0] for col in cursor.description ]
    return [ dict(zip(col_names, row)) for row in cursor ]


def _to_json(obj):
    if isinstance(obj, date | datetime | time):
        return obj.isoformat()
        
    raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


def make_response(status_code, body=None):
    headers = {
        'Access-Control-Allow-Origin': '*',
        'Access-Control-Allow-Methods': 'OPTIONS,POST,GET',
        'Access-Control-Allow-Headers': 'Origin, X-Requested-With, Content-Type, Accept'
    }
    
    response = {
        'statusCode': status_code,
        'headers': headers
    }
    
    if body:
        headers['Content-Type'] = 'application/json'
        response['body'] = json.dumps(body, default=_to_json)
    
    return response


def make_error_response(status_code, message, extra_fields={}):
    '''
    Create an error response object using the same format as the AWS API Gateway
    errors (return the error in a 'message' field).
    '''

    return make_response(status_code, {
        'message': message,
        **extra_fields
    })
