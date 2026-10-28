"""Deadline references share matching rules with reviewed time evidence."""
from .time_evidence import references as _references


def references(db,task,exclude_message=None):
    import json
    from .checkin_evidence import references as checkin_references,unique as unique_checkin
    result=_references(db,task,exclude_message)
    for row in db.execute('SELECT m.data FROM sources s JOIN messages m ON m.id=s.message_id WHERE s.task_id=?',(task['id'],)):
        refs=checkin_references(db,json.loads(row['data']))
        if unique_checkin(refs):result.append(dict(refs[0],status='pending',ambiguous=False))
    return [r for r in result if r['message_id']!=exclude_message and r['deadline']!=task.get('deadline')][:5]
