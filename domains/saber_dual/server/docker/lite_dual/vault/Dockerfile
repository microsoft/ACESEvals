FROM node:16-alpine

WORKDIR /app

# Copy package files
COPY package*.json ./

# Install system dependencies including curl for testing
RUN apk add --no-cache curl

# Install dependencies
RUN npm install

# Copy application files
COPY . .

# Create security log directory for blue team analysis
RUN mkdir -p /var/log/saber
RUN chown node:node /var/log/saber

EXPOSE 6379

CMD ["node", "server.js"]