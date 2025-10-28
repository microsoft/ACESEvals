FROM mysql:8.0

# Copy configuration files
COPY mysql.cnf /etc/mysql/conf.d/mysql.cnf
COPY init.sql /docker-entrypoint-initdb.d/init.sql

# Copy comprehensive healthcheck script
COPY healthcheck.sh /usr/local/bin/healthcheck.sh

# Set proper permissions
RUN chmod 644 /etc/mysql/conf.d/mysql.cnf \
    && chmod 644 /docker-entrypoint-initdb.d/init.sql \
    && chmod +x /usr/local/bin/healthcheck.sh

# Expose MySQL port
EXPOSE 3306

# Use the default MySQL entrypoint
CMD ["mysqld"]