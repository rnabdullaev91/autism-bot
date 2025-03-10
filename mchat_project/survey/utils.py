import logging


def calculate_mchat_score(answers):
    risk_questions_except = [2, 5, 12]
    score = 0
    for question_number, ans in answers:
        # ans = 'yes' or 'no'
        if question_number in risk_questions_except:
            if ans == 'yes':
                score += 1
        else:
            if ans == 'no':
                score += 1
    return score


def get_risk_level(score):
    logging.info(score)
    if score <= 2:
        return 'LOW'
    elif 3 <= score <= 7:
        return 'MEDIUM'
    else:
        return 'HIGH'
