import json
import logging

from auth import authenticator, ACCESS_TOKEN_SECRET_KEY

from main import *
from util import echo_request, make_error_response, make_response


def lambda_handler(event, context):
    
    if echo_request(event):
        return make_response(200, event)
    
    http_headers = { k.lower(): v for k, v in event['headers'].items() }
    
    # Compatibility code with production while all routes are checked for
    # modernization before switching the secret key in production and users
    # didn't have enough time to renew their tokens to include the tenant_id.
    # TODO: Remove
    if event['requestContext']['stage'] in ['prod', 'production']:
        access_token_secret_key = 'opaopaMIIA'
    else:
        access_token_secret_key = ACCESS_TOKEN_SECRET_KEY

    payload, error = authenticator(http_headers, event, secret_key=access_token_secret_key)
    if error:
        return error
    
    tenant_id = payload.get('tenant_id')
    if not tenant_id:
        if event['requestContext']['stage'] in ['prod', 'production']:  # TODO: Remove
            tenant_id = 'portal'
        else:
            return make_error_response(400, 'Missing tenant_id')

    if tenant_id == 'portal':
        tenant_id = 'public'
    
    conn = connect_to_db(tenant_id)
    if not conn:
        return make_error_response(401, f"Invalid schema: {tenant_id}")

    try:
        user_id = payload['id']
        
        payload, error = handle_profile(payload, conn) # Renew payload
        if error:
            return error
        
        login_log(user_id, conn)
        
        plan_data = get_user_subscription(user_id, conn)

        # Checking if the user has answered all mandatory questions of the survey
        survey_pendency_bool = checkSurveyPendency(user_id, plan_data, conn)
        
        permissions = check_page_access_permissions(user_id, plan_data, conn)
        
        payload['tenant_id'] = tenant_id
        payload['exams_id'] = [payload['exams_id']]
        payload['permissions'] = permissions
        payload['referral_code'] = 944234761407
        
        fill_admin_fields(conn, payload)
        
        return make_response(200, {
            'token': encodeData(payload, access_token_secret_key),
            'pending_profile_survey': survey_pendency_bool,
            'pending_user_exams': check_pending_user_exams(user_id, permissions, conn)
        })
        
    except Exception as e:
        logging.exception(f"Refresh token attempt failed for {payload['full_name']} - details: {str(e)}")
        return make_error_response(500, 'Internal server error')
