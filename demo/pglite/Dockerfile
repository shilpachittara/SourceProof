FROM node:22-alpine

WORKDIR /app

COPY package.json ./
RUN npm install --omit=dev

COPY server.mjs ./

ENV PGDATA=/data/pglite
ENV PGHOST=0.0.0.0
ENV PGPORT=5432

EXPOSE 5432

CMD ["npm", "start"]
