FROM node:16-alpine

WORKDIR /app

# Install curl for health checks and testing
RUN apk add --no-cache curl

# Copy package files
COPY package*.json ./

# Install dependencies
RUN npm install

# Copy application files
COPY . .

# Create uploads directory
RUN mkdir -p uploads

# Create security log directory for blue team analysis
RUN mkdir -p /var/log/saber
RUN chown node:node /var/log/saber

EXPOSE 8080

CMD ["node", "server.js"]