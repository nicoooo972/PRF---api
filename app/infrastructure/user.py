# app/infrastructure/user.py

import base64
import logging
from flask import jsonify, request
import uuid
import os
from passlib.hash import pbkdf2_sha256
from db import db
from flask_jwt_extended import create_access_token, jwt_required, \
    get_jwt_identity, \
    unset_jwt_cookies
from datetime import datetime, timedelta
from dotenv import load_dotenv
import boto3

load_dotenv()

secret_key = os.getenv("SECRET_KEY")


# Modèle d'utilisateur
class User:
    # Création compte utilisateur
    def register(self):
        user_data = request.json

        # Date de création de l'utilisateur
        now = datetime.now()
        # Formatage de la date -> dd/mm/YY H:M:S
        created_at = now.strftime("%d/%m/%Y %H:%M:%S")

        user = {
            "_id": uuid.uuid4().hex,
            "username": user_data.get('username'),
            "email": user_data.get('email'),
            "password": user_data.get('password'),
            "profile_picture": '',
            "created_at": created_at
        }

        if secret_key is None:
            return jsonify(
                {"error": "La clé secrète n'est pas définie !"}), 500

        try:
            secret_key_bytes = secret_key.encode('utf-8')
        except Exception as e:
            return jsonify(
                {
                    "error": "Erreur lors de l'encodage de la clé secrète en "
                             "bytes !",
                    "details": str(e)}), 500

        user["password"] = pbkdf2_sha256.hash(user['password'],
                                              salt=secret_key_bytes)

        if db.user.find_one({"email": user["email"]}):
            return jsonify({
                "error": "Cette adresse Email est déjà utilisée par un "
                         "utilisateur !"}), 400

        if db.user.insert_one(user):
            return jsonify(user), 200

        return jsonify({"error": "L'inscription a échouée."}), 400

    # Connexion compte utilisateur
    def login(self):
        login_data = request.json
        email = login_data.get('email')
        password = login_data.get('password')

        user = db.user.find_one({"email": email})
        if user and pbkdf2_sha256.verify(password, user['password']):
            access_token = create_access_token(identity=email,
                                               expires_delta=timedelta(
                                                   hours=24))  # Création du
            # token JWT avec l'email de l'utilisateur
            logging.info(
                f"Connexion réussie pour l'utilisateur avec l'email {email}.")
            return jsonify({"message": "Vous êtes connecté ! ",
                            "access_token": access_token}), 200  #
            # Retourner le token dans la réponse JSON
        else:
            logging.error("Tentative de connexion échouée.")
            return jsonify(
                {"error": "Adresse Email ou mot de passe incorrect !"}), 401

    # Récupérer les informations de l'utilisateur connecté
    @jwt_required()
    def get_user_info(self):
        current_user_email = get_jwt_identity()
        user = db.user.find_one({"email": current_user_email})
        if user:
            user["_id"] = str(user["_id"])  # Convertir ObjectId en string
            user.pop("password", None)  # Supprimer le champ mot de passe
            return jsonify(user), 200
        return jsonify({"error": "Utilisateur non trouvé."}), 404

    # Modifier les informations de l'utilisateur connecté
    @jwt_required()
    def update_user_info(self):
        current_user_email = get_jwt_identity()
        update_data = request.json
        user = db.user.find_one({"email": current_user_email})

        if not user:
            return jsonify({"error": "Utilisateur non trouvé."}), 404

        if "password" in update_data:
            try:
                secret_key_bytes = secret_key.encode('utf-8')
                update_data["password"] = pbkdf2_sha256.hash(
                    update_data["password"], salt=secret_key_bytes)
            except Exception as e:
                return jsonify({
                                   "error": "Erreur lors de l'encodage de la clé secrète en bytes.",
                                   "details": str(e)}), 500

        if "username" in update_data:
            if db.user.find_one({"username": update_data["username"]}):
                return jsonify({
                                   "error": "Ce pseudo est déjà utilisé par un autre utilisateur !"}), 400

        if "profile_picture" in update_data:
            # Extraire les données base64 du champ profile_picture
            profile_picture_data = update_data["profile_picture"]
            if not profile_picture_data.startswith("data:image/"):
                return jsonify({"error": "Format d'image invalide."}), 400

            # Décoder les données base64
            base64_encoded_data = profile_picture_data.split(",")[1]
            try:
                profile_picture_bytes = base64.b64decode(base64_encoded_data)
            except Exception as e:
                return jsonify({"error": "Erreur de décodage du base64.",
                                "details": str(e)}), 500

            # Configuration de la connexion S3
            s3 = boto3.client(
                's3',
                aws_access_key_id=os.getenv('AWS_ACCESS_KEY_ID'),
                aws_secret_access_key=os.getenv('AWS_SECRET_ACCESS_KEY'),
                region_name=os.getenv('AWS_REGION')
            )
            bucket_name = "instant-playhub-storage"
            profile_picture_key = f"user/profile_picture/{user['_id']}.jpg"

            # Téléverser l'image sur S3
            try:
                s3.put_object(Bucket=bucket_name, Key=profile_picture_key,
                              Body=profile_picture_bytes, ACL='public-read')
            except Exception as e:
                return jsonify({
                                   "error": "Erreur lors du téléversement de la photo de profil.",
                                   "details": str(e)}), 500

            # Mettre à jour le champ profile_picture avec l'URL de l'image sur S3
            update_data[
                "profile_picture"] = f"https://{bucket_name}.s3.{os.getenv('AWS_REGION')}.amazonaws.com/{profile_picture_key}"

        db.user.update_one({"email": current_user_email},
                           {"$set": update_data})
        return jsonify({
                           "message": "Informations de l'utilisateur mises à jour avec succès."}), 200

    # Supprimer le compte de l'utilisateur connecté
    @jwt_required()
    def delete_account(self):
        current_user_email = get_jwt_identity()
        user = db.user.find_one({"email": current_user_email})

        if not user:
            return jsonify({"error": "Utilisateur non trouvé."}), 404

        db.user.delete_one({"email": current_user_email})
        return jsonify(
            {"message": "Compte utilisateur supprimé avec succès."}), 200

    # Récupérer les informations de tous les utilisateurs
    def get_all_users(self):
        users = list(db.user.find({}, {"_id": 0,
                                       "password": 0}))  # on exclue le champ 'password'
        return jsonify({"users": users}), 200

    # Déconnexion compte utilisateur avec expiration du token JWT
    @jwt_required()
    def logout(self):
        unset_jwt_cookies()  # Expiration du token JWT
        return jsonify({"message": "Vous êtes déconnecté."}), 200


user = User()
