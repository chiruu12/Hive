Write tests BEFORE implementation. Follow this cycle:

1. Write a failing test that describes the desired behavior
2. Run the test — confirm it fails for the right reason
3. Write the minimum code to make it pass
4. Refactor if needed, keeping tests green
5. Commit the test and implementation together

Use descriptive test names: `test_user_cannot_login_with_expired_token` not `test_login_2`.
One assertion per test when possible. Test edge cases, not just the happy path.
