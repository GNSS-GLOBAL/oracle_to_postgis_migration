SELECT USER AS current_user,
    SYS_CONTEXT('USERENV', 'CON_NAME') AS database_container
FROM dual;