# Use an official Node runtime as a parent image
FROM node:18-alpine

# Set the working directory in the container
WORKDIR /app

# Copy package.json and package-lock.json
COPY package*.json ./

# Install dependencies
RUN npm install

# Copy the rest of the application code
COPY . .

# Build the app for production (optional, if we use nginx)
# RUN npm run build

# Expose port
EXPOSE 3000

# Start the app
CMD ["npm", "start"]
