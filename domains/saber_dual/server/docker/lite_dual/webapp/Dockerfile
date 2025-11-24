FROM php:8.0-apache

# Install system packages including iptables for blue team security operations
RUN apt-get update && apt-get install -y \
    iptables \
    && rm -rf /var/lib/apt/lists/*

# Install mysqli extension
RUN docker-php-ext-install mysqli && docker-php-ext-enable mysqli

# Enable Apache modules (rewrite for URL routing, headers for .htaccess directives)
RUN a2enmod rewrite
RUN a2enmod headers

# Copy application files
COPY ./src/ /var/www/html/

# Copy entrypoint script
COPY ./entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Create security log directory for blue team analysis
RUN mkdir -p /var/log/saber
RUN chown www-data:www-data /var/log/saber
RUN chmod 755 /var/log/saber

# Set proper permissions
RUN chown -R www-data:www-data /var/www/html/
RUN chmod -R 755 /var/www/html/

# Enable Apache error logging
RUN echo "LogLevel warn" >> /etc/apache2/apache2.conf
RUN echo "ErrorLog /var/log/apache2/error.log" >> /etc/apache2/apache2.conf
RUN echo "CustomLog /var/log/apache2/access.log combined" >> /etc/apache2/apache2.conf

EXPOSE 80

# Use custom entrypoint that ensures proper logging setup
ENTRYPOINT ["/entrypoint.sh"]