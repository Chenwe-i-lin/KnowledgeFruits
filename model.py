import peewee
import time
from datetime import datetime
from time import strftime
import base
import os
import simplejson
import base64
import uuid
import rsa
import binascii
import password
from OpenSSL.crypto import load_privatekey, FILETYPE_PEM, sign
import hashlib

config = base.Dict2Object(simplejson.loads(open("./data/config.json").read()))

db = {}
db['global'] = peewee.__dict__[config.database.type](config.database.connect_info.global_db, **config.database.globalinfo)
db['cache'] = peewee.__dict__[config.database.type](config.database.connect_info.cache, **config.database.globalinfo)
class db_user(peewee.Model):
    uuid = peewee.CharField(default=str(uuid.uuid4()))
    email = peewee.CharField()
    password = peewee.CharField()
    passwordsalt = peewee.CharField()
    #playername = peewee.CharField()
    selected = peewee.CharField(null=True)

    class Meta:
        database = db['global']

class db_token(peewee.Model):
    accessToken = peewee.CharField()
    clientToken = peewee.CharField()
    status = peewee.CharField(default=0)
    bind = peewee.CharField(null=True)
    email = peewee.CharField()
    setuptime = peewee.TimestampField(default=time.time())

    class Meta:
        database = db['global']

class db_profile(peewee.Model):
    format_id = peewee.CharField(max_length=32, default=str(uuid.uuid4()).replace('-',''))
    uuid = peewee.CharField(max_length=32)
    name = peewee.CharField()
    #texture = peewee.CharField()
    type = peewee.CharField(default='SKIN')
    model = peewee.CharField(default='STEVE')
    hash = peewee.CharField()
    time = peewee.CharField(default=str(int(time.time())))
    createby = peewee.CharField() # 谁创建的角色?  邮箱
    ismain = peewee.BooleanField(default=True)
    #beselected = peewee.BooleanField(default=False)

    class Meta:
        database = db['global']

class ms_serverjoin(peewee.Model):
    AccessToken = peewee.CharField(32)
    SelectedProfile = peewee.CharField()
    ServerID = peewee.CharField()
    RemoteIP = peewee.CharField(16, default='0.0.0.0')
    time = peewee.CharField(default=time.time())
    class Meta:
        database = db['cache']

class textures(peewee.Model):
    userid = peewee.CharField(32)
    textureid = peewee.CharField(default=str(uuid.uuid4()))
    photoname = peewee.CharField()
    height = peewee.IntegerField(default=32)
    width = peewee.IntegerField(default=64)
    type = peewee.CharField(default='SKIN')
    model = peewee.CharField(default='STEVE')
    hash = peewee.CharField()
    
    class Meta:
        database = db['global']

'''
class banner(peewee.Model):
    email = peewee.CharField()
    accessToken = peewee.CharField(max_length=32, null=True)
    profileuuid = peewee.CharField()
    inittime = peewee.TimestampField(default=int(time.time())) # time.mktime(datetime.now().timetuple())
    timeout = peewee.TimestampField()
    class Meta:
        database = db['global']
'''
def CreateProfile(profile, pngname):
    OfflineUUID = base.OfflinePlayerUUID(profile.name)
    Name = profile.name
    hashvalue = base.PngBinHash(config.TexturePath + pngname)
    db = db_profile(uuid=OfflineUUID, name=Name, hash=hashvalue)
    db.save()
    os.rename(config.TexturePath + pngname, config.TexturePath + hashvalue + ".png")

def format_texture(profile, unMetaData=False):
    OfflineUUID = base.OfflinePlayerUUID(profile.name).replace("-",'')
    db_data = db_profile.get(uuid=OfflineUUID)
    db_datas = db_profile.select().where(db_profile.uuid==OfflineUUID)
    #print(type(db_data.time))
    IReturn = {
        "timestamp" : round(float(db_data.time)),
        'profileId' : db_data.format_id,
        'profileName' : db_data.name,
        'textures' : {
            i.type : {
                "url" : config.HostUrl + "/texture/" + i.hash,
                "metadata" : {
                    'model' : {"STEVE": 'default', "ALEX": 'slim'}[i.model]
                } if i.type == 'SKIN' else {}
            } for i in db_datas
        }
    }
    if unMetaData:
        for i in IReturn['textures'].keys():
            del IReturn['textures'][i]["metadata"]
    return IReturn

def format_profile(profile, unsigned=False, Properties=False, unMetaData=False, BetterData=False):
    def sign_self(data, key_file):
        key_file = open(key_file, 'r').read()
        key = rsa.PrivateKey.load_pkcs1(key_file.encode('utf-8'))
        return bytes(base64.b64encode(rsa.sign(data.encode("utf-8"), key, 'SHA-1'))).decode("utf-8")
    if BetterData:
        if not [True, False][profile.type == "SKIN" and profile.model == "ALEX"]:
            unMetaData = False
        else:
            unMetaData = True
    textures = simplejson.dumps(format_texture(profile, unMetaData))
    IReturn = {
        "id" : profile.format_id,
        "name" : profile.name,
    }
    if Properties:
        IReturn['properties'] = [
            {
                "name": 'textures',
                'value' : base64.b64encode(textures.encode("utf-8")).decode("utf-8"),
            }
        ]
        if not unsigned:
            for i in range(len(IReturn['properties'])):
                IReturn['properties'][i]['signature'] = sign_self(IReturn['properties'][i]['value'], "./data/rsa.pem")
    return IReturn

def is_validate(AccessToken, ClientToken=None):
    try:
        if not ClientToken:
            try:
                result = db_token.get(db_token.accessToken == AccessToken)
            except Exception as e:
                if "db_tokenDoesNotExist" == e.__class__.__name__:
                    return False
        else:
            try:
                result = db_token.get(db_token.accessToken == AccessToken & db_token.clientToken == ClientToken)
            except Exception as e:
                if "db_tokenDoesNotExist" == e.__class__.__name__:
                    result = db_token.get(db_token.accessToken == AccessToken)
    except Exception as e:
        if "db_tokenDoesNotExist" == e.__class__.__name__:
            return False
        raise e
    else:
        if result.status in [2,1]:
            return False
        else:
            return True

def gettoken(AccessToken, ClientToken=None):
    try:
        if not ClientToken:
            try:
                result = db_token.get(db_token.accessToken == AccessToken)
            except Exception as e:
                if "db_tokenDoesNotExist" == e.__class__.__name__:
                    return False
        else:
            try:
                result = db_token.get(db_token.accessToken == AccessToken & db_token.clientToken == ClientToken)
            except Exception as e:
                if "db_tokenDoesNotExist" == e.__class__.__name__:
                    result = db_token.get(db_token.accessToken == AccessToken)
    except Exception as e:
        if "db_tokenDoesNotExist" == e.__class__.__name__:
            return False
        raise e
    else:
        if result.status in [2,1]:
            return False
        else:
            return result

def getprofile(name):
    try:
        result = db_profile.select().where(db_profile.name == name)
    except Exception as e:
        if "db_profileDoesNotExist" == e.__class__.__name__:
            return False
        raise e
    else:
        return result

def getuser(email):
    try:
        result = db_user.select().where(db_user.email == email)
    except Exception as e:
        if "db_userDoesNotExist" == e.__class__.__name__:
            return False
        raise e
    else:
        return result

def findprofilebyid(fid):
    try:
        result = db_profile.select().where(db_profile.format_id == fid)
    except Exception as e:
        if "db_profileDoesNotExist" == e.__class__.__name__:
            return False
        raise e
    else:
        return result.get()

def format_user(user):
    return {
        'id' : user.uuid,
        'properties' : []
    }

def NewProfile(Playername, User, Png, Type='SKIN', Model="STEVE"):
    Email = User.email
    db_p = db_profile(uuid=base.OfflinePlayerUUID(Playername).replace('-',''), name=Playername, hash=base.PngBinHash(config.texturepath + Png), createby=Email, type=Type, model=Model)
    print(config.texturepath + Png)
    os.rename(config.texturepath + Png, config.texturepath + base.PngBinHash(config.texturepath + Png) + ".png")
    db_p.save()

def NewUser(email, passwd):
    salt = base.CreateSalt(length=8)
    db_user(
        email=email,
        password=password.crypt(passwd, salt),
        passwordsalt=salt
    ).save()

if __name__ == '__main__':
    #NewUser("test@gmail.com", "asd123456")
    #NewUser("test3@to2mbn.org", "asd123456")
    #NewProfile("testplayer", db_user.get(email='test3@to2mbn.org'), "490bd08f1cc7fce67f2e7acb877e5859d1605f4ffb0893b07607deae5e05becc.png", Model='ALEX')
    #NewProfile("testplayer1", db_user.get(email='test3@to2mbn.org'), "1cd0db978f11733c4d6480fff46dd3530518e82eee23eb1ecb568550a35553ad.png", Type='CAPE')
    print(db_token.create_table())
    #print(db['global'].connect())
    #print(dbinfo['attr']['database'])