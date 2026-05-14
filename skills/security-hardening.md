Review code for security issues. Check for:

- Input validation: never trust external input, validate at boundaries
- Injection: SQL injection, command injection, path traversal
- Authentication: secrets in env vars not code, no hardcoded credentials
- Authorization: verify permissions before actions
- Data exposure: don't log sensitive data, sanitize error messages

When reviewing, flag severity (critical/high/medium/low) and provide fix suggestions.
