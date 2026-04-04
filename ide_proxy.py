#!/usr/bin/env python3
import sys
import json
import db

def main():
    if len(sys.argv) < 2:
        return

    cmd = sys.argv[1]

    if cmd == "get":
        job = db.get_pending_job()
        print(json.dumps(job) if job else "null")
    
    elif cmd == "complete":
        if len(sys.argv) < 3:
            return
        job_id = int(sys.argv[2])
        response_text = sys.stdin.read()
        db.complete_job(job_id, response_text)
    
    elif cmd == "fail":
        if len(sys.argv) < 3:
            return
        job_id = int(sys.argv[2])
        error_text = sys.stdin.read()
        db.fail_job(job_id, error_text)

if __name__ == "__main__":
    main()
