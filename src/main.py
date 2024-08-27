import json

import jwt
import hashlib

import psycopg2.extras as extras

from dbconn import connect_to_db
from util import fetchone_to_dict

import logging


def checkUser(user_id, conn):
    sql = """
        select u.id, u.full_name, u.email, up.course, case when s.expiry_date < CURRENT_TIMESTAMP then null else s.plan_id end, p.exams_id as exams_id 
        from "user" u
        left join user_profile up 
        on up.user_id = u.id
        left join subscriptions s
        on u.id = s.user_id 
        left join "plans" p
        on p.id = s.plan_id 
        where u.id = %(user_id)s
        order by s.created_at desc
        limit 1
    ;"""
    
    # Executar a consulta com a lista de valores como um parâmetro
    with conn:
        with conn.cursor() as cursor:
            cursor.execute(sql, {'user_id': user_id})
            
            # Obter os resultados
            resultados = cursor.fetchall()
            
            if len(resultados) == 0:
                return False
            
            nomes_colunas = [desc[0] for desc in cursor.description]
            
            out = dict(zip(nomes_colunas, resultados[0]))
            
            return out


def fill_admin_fields(conn, payload):
    with conn:
        with conn.cursor() as cursor:
            cursor.execute('''
                SELECT 
                    i.type AS institution_type,
                    i.admin_user_id
                FROM institution i
            ''')
            
            assert cursor.rowcount == 1
            
            data = cursor.fetchone()
            
            payload['institution_type'] = data['institution_type']
            payload['is_admin'] = (payload['id'] == data['admin_user_id'])


def login_log(user_id, conn):
    sql = """
        select 
        	max(timestamp) >= current_timestamp - interval '1 hour' 
            as logged_recently
        from login_log
        where user_id = %(user_id)s
    """
    sql2 = """
        Insert into
            login_log (user_id, login_source)
            values (%(id)s, 'access_token')
    """

    with conn:
        with conn.cursor() as cursor:
            cursor.execute(sql, {'user_id': user_id})

            result = fetchone_to_dict(cursor)

            if result['logged_recently']:
                return
            cursor.execute(sql2, {'id' : user_id})


# Codificar um token JWT
def encodeData(payload,secret_key):
    return jwt.encode(payload, secret_key, algorithm='HS256')
    
        
def checkSurveyPendency(user_id, plan_data, conn):
    if not plan_data['permissions']['user_exams']:
        return False

    query = '''
        select 
        	gender, 
        	education_level, 
        	high_school_system, 
        	marketing_channel, 
        	study_techniques, 
        	subjects_to_improve, 
        	study_hours
        from user_profile_survey
        where user_id = %(user_id)s
    '''
    
    with conn:
        with conn.cursor() as cursor:
            cursor.execute(query, { 'user_id': user_id })
            mandatory_answers = cursor.fetchall()
            
            
            if mandatory_answers == []: # User isn't in table user_profile_survey
                return True
            elif None in mandatory_answers[0]: # User is in table user_profile_survey, but hasn't answered a mandatory question
                return True
            else:
                return False


def _select_user_history(user_id, conn):
    with conn:
        with conn.cursor() as cursor:
            sql = '''
                select
                	exists(select 1 from user_sub_topic_level
                	       where user_id = %(user_id)s
        	        ) as has_performance_history,
                	exists(select 1 from favorites
                	       where user_id = %(user_id)s
            	    ) as has_favorite_videos,
                	exists(select 1 from user_placement_test
                	       where user_id = %(user_id)s
            	    ) as has_user_placement_tests,
                	exists(
                		select 1 from activities
                		where user_id = %(user_id)s
                		and questionnaire_id is not null
                		or user_essay_id is not null
                	) as has_activity_history
            '''

            cursor.execute(sql, { 'user_id': user_id })
            
            return fetchone_to_dict(cursor)


def check_page_access_permissions(user_id, plan_data, conn):
    permissions = plan_data['permissions']
    user_history = _select_user_history(user_id, conn)

    if user_history['has_performance_history']:
        permissions['performance'] = True

    if user_history['has_favorite_videos']:
        permissions['favorite_videos'] = True
    
    # TODO: Read-only access for history view if user has no active subscription

    return permissions


def check_pending_user_exams(user_id, permissions, conn):
    if not permissions.get('user_exams'):
        return False

    sql = '''
        SELECT NOT EXISTS(
            SELECT 1
            FROM user_course
            WHERE user_id = %(user_id)s
        )
    '''
    
    with conn:
        with conn.cursor() as cursor:
            cursor.execute(sql, { 'user_id': user_id })
            return cursor.fetchone()[0]


def get_user_subscription(user_id, conn):
    sql = '''
        select
            p.permission_id,
        	case 
        		when s.expiry_date >= now() then TRUE
        		when s.expiry_date < now() then FALSE
        		when s.canceled_at is not null then FALSE
        		when ph.status = 'pending' then FALSE 
        		WHEN ph.id IS NULL OR ph.status = 'paid' then TRUE
        		else FALSE
        	end as status
        from subscriptions s
        join plans p on s.plan_id = p.id
        left join payment_history ph on ph.subscriptions_id = s.id
        where s.user_id = %(user_id)s
        order by s.id desc, ph.id desc 
        limit 1
    '''
    
    with conn:
        with conn.cursor() as cursor:
            cursor.execute(sql, { 'user_id': user_id })
            data = fetchone_to_dict(cursor)

            if data and data['status']:
                permission_id = data['permission_id']
            else:
                permission_id = 0  # Default permissions

            cursor.execute('''
                SELECT
                    availability, study_plan, questions, essay, performance,
                    activity_history, plans, placement_test, user_exams,
                    favorite_videos, notifications, profile,
                    on_demand_activities, virtual_tutor
                FROM permission
                WHERE id = %(permission_id)s
            ''', {
                'permission_id': permission_id
            })
            
            permissions = fetchone_to_dict(cursor)

    return { 'permissions': permissions }


def handle_profile(payload, conn):
    
    iam = checkUser(payload['id'], conn)
    
    if not iam:
        logging.warning(f"Login attempt failed for {username}: User not found")
        return None, make_error_response(401, "Invalid username or password")

    return iam, None